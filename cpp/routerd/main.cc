#include <nlohmann/json.hpp>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cerrno>
#include <fcntl.h>
#include <iostream>
#include <optional>
#include <filesystem>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>
#include <unistd.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/wait.h>

namespace {

using json = nlohmann::json;

std::string IsoNow() {
  // Keep this simple; downstream treats this as an opaque proto-JSON timestamp string.
  using namespace std::chrono;
  const auto now = system_clock::now();
  const auto secs = time_point_cast<seconds>(now);
  const auto t = system_clock::to_time_t(secs);
  std::tm tm{};
#if defined(_WIN32)
  gmtime_s(&tm, &t);
#else
  gmtime_r(&t, &tm);
#endif
  char buf[64];
  std::snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02dZ",
                tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                tm.tm_hour, tm.tm_min, tm.tm_sec);
  return std::string(buf);
}

void WriteLine(const json& obj) {
  std::cout << obj.dump() << "\n";
  std::cout.flush();
}

json JsonRpcError(json id, std::string message) {
  return json{
      {"jsonrpc", "2.0"},
      {"id", std::move(id)},
      {"error", json{{"code", -32000}, {"message", std::move(message)}}},
  };
}

json JsonRpcResult(json id, json result) {
  return json{
      {"jsonrpc", "2.0"},
      {"id", std::move(id)},
      {"result", std::move(result)},
  };
}

json UiEvent(std::string kind,
             std::string request_id,
             std::string route_name,
             std::string message,
             std::string health = "HEALTH_STATE_UNKNOWN",
             std::optional<json> inventory = std::nullopt) {
  json params{
      {"kind", std::move(kind)},
      {"requestId", std::move(request_id)},
      {"routeName", std::move(route_name)},
      {"message", std::move(message)},
      {"health", std::move(health)},
      {"observedAt", IsoNow()},
  };
  if (inventory.has_value()) {
    params["inventory"] = std::move(*inventory);
  }
  return json{{"jsonrpc", "2.0"}, {"method", "ui/event"}, {"params", std::move(params)}};
}

struct InventorySidecar {
  explicit InventorySidecar(std::string python = "python3") : python_(std::move(python)) {}

  ~InventorySidecar() { Stop(); }

  json Request(std::string_view method, const json& params) {
    EnsureStarted();

    const int req_id = next_id_++;
    json req{
        {"jsonrpc", "2.0"},
        {"id", req_id},
        {"method", std::string(method)},
        {"params", params},
    };
    const std::string line = req.dump() + "\n";
    if (!WriteAll(line)) {
      Restart("inventory sidecar write failed");
      throw std::runtime_error("inventory sidecar write failed");
    }

    // Read responses until we see our id.
    for (;;) {
      auto maybe_line = ReadLine();
      if (!maybe_line.has_value()) {
        Restart("inventory sidecar closed stdout");
        throw std::runtime_error("inventory sidecar closed stdout");
      }
      json resp;
      try {
        resp = json::parse(*maybe_line);
      } catch (...) {
        continue;
      }
      if (!resp.is_object()) continue;
      if (resp.value("id", -1) != req_id) continue;
      if (resp.contains("error")) {
        const auto& err = resp["error"];
        Restart("inventory sidecar returned error");
        throw std::runtime_error(err.value("message", "inventory sidecar error"));
      }
      return resp.value("result", json::object());
    }
  }

 private:
  std::string python_;
  pid_t pid_ = -1;
  int stdin_fd_ = -1;
  int stdout_fd_ = -1;
  int next_id_ = 1;

  void EnsureStarted() {
    if (pid_ > 0 && stdin_fd_ >= 0 && stdout_fd_ >= 0) return;
    Start();
  }

  [[noreturn]] void Restart(std::string_view why) {
    (void)why;
    Stop();
    Start();
    throw std::runtime_error("inventory sidecar restarted");
  }

  void Stop() {
    if (stdin_fd_ >= 0) {
      ::close(stdin_fd_);
      stdin_fd_ = -1;
    }
    if (stdout_fd_ >= 0) {
      ::close(stdout_fd_);
      stdout_fd_ = -1;
    }
    if (pid_ > 0) {
      ::kill(pid_, SIGTERM);
      int status = 0;
      (void)::waitpid(pid_, &status, 0);
      pid_ = -1;
    }
    next_id_ = 1;
  }

  static std::string StrError() {
    return std::string(std::strerror(errno));
  }

  void Start() {
    const auto cwd = std::filesystem::current_path();
    const auto src_root = cwd / "src";
    std::string pythonpath;
    if (std::filesystem::is_directory(src_root)) {
      pythonpath = src_root.string();
    }

    int to_child[2];
    int from_child[2];
    if (::pipe(to_child) != 0) {
      throw std::runtime_error("pipe() failed: " + StrError());
    }
    if (::pipe(from_child) != 0) {
      ::close(to_child[0]);
      ::close(to_child[1]);
      throw std::runtime_error("pipe() failed: " + StrError());
    }

    pid_t child = ::fork();
    if (child < 0) {
      ::close(to_child[0]);
      ::close(to_child[1]);
      ::close(from_child[0]);
      ::close(from_child[1]);
      throw std::runtime_error("fork() failed: " + StrError());
    }

    if (child == 0) {
      // Child: connect pipes to stdin/stdout.
      ::dup2(to_child[0], STDIN_FILENO);
      ::dup2(from_child[1], STDOUT_FILENO);
      // Leave stderr inherited so crashes are visible to operator logs.

      ::close(to_child[0]);
      ::close(to_child[1]);
      ::close(from_child[0]);
      ::close(from_child[1]);

      if (!pythonpath.empty()) {
        ::setenv("PYTHONPATH", pythonpath.c_str(), 1);
      }

      const char* argv[] = {
          python_.c_str(),
          "-m",
          "services.inventory.daemon.main",
          nullptr,
      };
      ::execvp(argv[0], const_cast<char* const*>(argv));
      // If exec fails:
      std::fprintf(stderr, "execvp failed: %s\n", std::strerror(errno));
      std::_Exit(127);
    }

    // Parent: keep write end to child stdin, read end from child stdout.
    ::close(to_child[0]);
    ::close(from_child[1]);

    pid_ = child;
    stdin_fd_ = to_child[1];
    stdout_fd_ = from_child[0];

    // Make reads non-blocking? Keep blocking for simplicity; readline blocks until '\n'.
    // Ensure fds are in blocking mode.
    (void)::fcntl(stdout_fd_, F_SETFL, ::fcntl(stdout_fd_, F_GETFL) & ~O_NONBLOCK);
  }

  bool WriteAll(const std::string& s) {
    const char* p = s.data();
    size_t remaining = s.size();
    while (remaining > 0) {
      const ssize_t n = ::write(stdin_fd_, p, remaining);
      if (n < 0) {
        if (errno == EINTR) continue;
        return false;
      }
      p += n;
      remaining -= static_cast<size_t>(n);
    }
    return true;
  }

  std::optional<std::string> ReadLine() {
    std::string out;
    out.reserve(4096);
    for (;;) {
      char ch = '\0';
      const ssize_t n = ::read(stdout_fd_, &ch, 1);
      if (n == 0) {
        return std::nullopt;
      }
      if (n < 0) {
        if (errno == EINTR) continue;
        return std::nullopt;
      }
      if (ch == '\n') {
        return out;
      }
      out.push_back(ch);
      if (out.size() > 1024 * 1024) {
        // Guardrail: avoid unbounded memory if sidecar goes off the rails.
        return std::nullopt;
      }
    }
  }
};

struct RouterState {
  std::string active_route;
  bool route_list_cache_complete = false;
  std::vector<std::string> route_list_order;
};

struct CachedSnapshot {
  json snapshot;
  std::chrono::steady_clock::time_point observed;
  int ttl_ms = 0;
  int generation = 0;
};

bool SnapshotIsFresh(const CachedSnapshot& entry) {
  if (entry.ttl_ms <= 0) return true;
  const auto age = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - entry.observed);
  return age.count() <= entry.ttl_ms;
}

std::string BackendNameFromEnum(const std::string& backend_enum) {
  if (backend_enum == "SERVING_BACKEND_STUDIO") return "studio";
  if (backend_enum == "SERVING_BACKEND_LLAMACPP") return "llamacpp";
  if (backend_enum == "SERVING_BACKEND_OPENAI") return "openai";
  if (backend_enum == "SERVING_BACKEND_SSH_OPENAI") return "ssh_openai";
  if (backend_enum == "SERVING_BACKEND_VLLM") return "vllm";
  return "";
}

json EntryFromSnapshot(const json& snapshot) {
  const std::string name = snapshot.value("source", "");
  const json endpoint = snapshot.value("endpoint", json::object());
  const std::string backend = BackendNameFromEnum(endpoint.value("backend", ""));

  std::string model_name;
  const json avail = snapshot.value("availableModels", json::array());
  if (avail.is_array() && !avail.empty() && avail[0].is_object()) {
    const json ref = avail[0].value("ref", json::object());
    model_name = ref.value("name", "");
  }

  const std::string resolved = endpoint.value("nodeName", "");
  const std::string description = resolved;

  return json{
      {"name", name},
      {"kind", "route"},
      {"backend", backend},
      {"model", model_name},
      {"description", description},
      {"resolved", resolved},
      {"aliases", json::array()},
  };
}

json RouteFromSnapshot(const json& snapshot) {
  const std::string name = snapshot.value("source", "");
  const json endpoint = snapshot.value("endpoint", json::object());
  const std::string backend_enum = endpoint.value("backend", "");
  const std::string backend = BackendNameFromEnum(backend_enum);

  json model_ref = json::object();
  std::string display_name;
  std::string role;
  bool tools_enabled = false;
  int max_tokens = 0;

  const json avail = snapshot.value("availableModels", json::array());
  if (avail.is_array() && !avail.empty() && avail[0].is_object()) {
    model_ref = avail[0].value("ref", json::object());
    display_name = avail[0].value("displayName", "");
    role = avail[0].value("role", "");
    tools_enabled = avail[0].value("toolsEnabled", false);
    max_tokens = avail[0].value("maxTokens", 0);
  }
  if (!model_ref.is_object()) model_ref = json::object();

  json route{
      {"name", name},
      {"displayName", display_name.empty() ? name : display_name},
      {"model", model_ref},
      {"backend", backend_enum.empty() ? "SERVING_BACKEND_UNSPECIFIED" : backend_enum},
      {"inferenceEndpoint", endpoint},
      {"controlEndpoint", json::object()},
      {"aliases", json::array()},
      {"autoLoad", backend == "studio"},
      {"preferred", name == "oracle-pro-5090"},
      {"health", snapshot.value("health", "HEALTH_STATE_UNKNOWN")},
      {"detail", snapshot.value("detail", "")},
      {"generation", snapshot.value("generation", 0)},
      {"toolsEnabled", tools_enabled},
      {"role", role},
      {"maxTokens", max_tokens},
  };
  return route;
}

json HandleRouteList(InventorySidecar& inventory,
                     RouterState& state,
                     std::unordered_map<std::string, CachedSnapshot>& cache) {
  // Use cache when all known entries are still fresh; otherwise refresh via inventory/query.
  bool cache_ok = state.route_list_cache_complete && !state.route_list_order.empty();
  if (cache_ok) {
    for (const auto& name : state.route_list_order) {
      const auto found = cache.find(name);
      if (found == cache.end()) {
        cache_ok = false;
        break;
      }
      const auto& entry = found->second;
      if (!SnapshotIsFresh(entry)) {
        cache_ok = false;
        break;
      }
    }
  }

  std::vector<json> snapshots;
  if (cache_ok) {
    snapshots.reserve(state.route_list_order.size());
    for (const auto& name : state.route_list_order) {
      snapshots.push_back(cache.at(name).snapshot);
    }
  } else {
    const json result = inventory.Request("inventory/query", json::object());
    state.route_list_order.clear();
    state.route_list_cache_complete = true;
    if (result.contains("snapshots") && result["snapshots"].is_array()) {
      for (const auto& item : result["snapshots"]) {
        if (!item.is_object()) continue;
        const std::string source = item.value("source", "");
        CachedSnapshot entry;
        entry.snapshot = item;
        entry.observed = std::chrono::steady_clock::now();
        entry.ttl_ms = item.value("ttlMs", 0);
        entry.generation = item.value("generation", 0);
        if (!source.empty()) {
          cache[source] = std::move(entry);
          state.route_list_order.push_back(source);
        }
        snapshots.push_back(item);
      }
    }
  }

  std::vector<json> entries;
  std::vector<json> routes;
  entries.reserve(snapshots.size());
  routes.reserve(snapshots.size());
  for (const auto& snap : snapshots) {
    entries.push_back(EntryFromSnapshot(snap));
    routes.push_back(RouteFromSnapshot(snap));
  }

  json active;
  active["backend"] = "";  // routerd does not probe current backend identity yet
  active["model"] = "";
  active["studio_node"] = "";
  active["llamacpp_node"] = "";

  json payload;
  payload["active"] = active;
  payload["entries"] = entries;
  payload["active_route"] = state.active_route;
  payload["routes"] = routes;
  return payload;
}

json HandleRouteStatus(const RouterState& state, const json& params) {
  const std::string route = params.value("route", "");
  json payload;
  payload["route"] = route.empty() ? state.active_route : route;
  payload["activeRoute"] = state.active_route;
  return payload;
}

json HandleRouteSelect(RouterState& state, const json& params) {
  const std::string route = params.value("route", "");
  if (route.empty()) {
    throw std::runtime_error("route/select requires params.route");
  }
  state.active_route = route;
  json payload;
  payload["accepted"] = true;
  payload["route"] = route;
  payload["message"] = "Route set to " + route;
  return payload;
}

}  // namespace

int main(int argc, char** argv) {
  (void)argc;
  (void)argv;

  RouterState state;
  state.active_route = "";
  InventorySidecar inventory;
  std::unordered_map<std::string, CachedSnapshot> snapshot_cache;

  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty()) continue;

    json req;
    try {
      req = json::parse(line);
    } catch (...) {
      continue;
    }
    if (!req.is_object()) continue;
    if (req.value("jsonrpc", "") != "2.0") continue;
    json id = req.contains("id") ? req["id"] : json(nullptr);
    const std::string method = req.value("method", "");
    const json params = req.contains("params") && req["params"].is_object() ? req["params"] : json::object();

    try {
      if (method == "route/list") {
        WriteLine(JsonRpcResult(id, HandleRouteList(inventory, state, snapshot_cache)));
        continue;
      }
      if (method == "route/status") {
        WriteLine(JsonRpcResult(id, HandleRouteStatus(state, params)));
        continue;
      }
      if (method == "route/select") {
        const std::string route = params.value("route", "");
        const std::string request_id = id.is_null() ? "" : id.dump();
        if (!route.empty()) {
          WriteLine(UiEvent("UI_EVENT_KIND_ROUTE_SELECTED", request_id, route, "Route set to " + route));
          WriteLine(UiEvent("UI_EVENT_KIND_INVENTORY_REFRESHING", request_id, route, "Inventory refreshing"));
        }
        WriteLine(JsonRpcResult(id, HandleRouteSelect(state, params)));
        // For now, emit "updated" after select by pulling one snapshot (active route only).
        // This keeps the event stream shape aligned with the Python expectation.
        if (!route.empty()) {
          json snapshot = inventory.Request("inventory/refresh", json{{"route", route}});
          const std::string health = snapshot.value("health", "HEALTH_STATE_UNKNOWN");
          CachedSnapshot entry;
          entry.snapshot = snapshot;
          entry.observed = std::chrono::steady_clock::now();
          entry.ttl_ms = snapshot.value("ttlMs", 0);
          entry.generation = snapshot.value("generation", 0);
          snapshot_cache[route] = std::move(entry);
          WriteLine(UiEvent("UI_EVENT_KIND_INVENTORY_UPDATED", request_id, route, "Inventory updated", health,
                            snapshot));
        }
        continue;
      }

      WriteLine(JsonRpcError(id, "Unknown method: " + method));
    } catch (const std::exception& exc) {
      WriteLine(JsonRpcError(id, exc.what()));
    }
  }
  return 0;
}
