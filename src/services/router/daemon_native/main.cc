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
      Restart();
      throw std::runtime_error("inventory sidecar write failed");
    }
    for (;;) {
      auto maybe_line = ReadLine();
      if (!maybe_line.has_value()) {
        Restart();
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
        Restart();
        const auto& err = resp["error"];
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

  static std::string StrError() { return std::string(std::strerror(errno)); }

  void EnsureStarted() {
    if (pid_ > 0 && stdin_fd_ >= 0 && stdout_fd_ >= 0) return;
    Start();
  }

  void Restart() {
    Stop();
    Start();
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

  void Start() {
    const auto cwd = std::filesystem::current_path();
    const auto src_root = cwd / "src";
    std::string pythonpath;
    if (std::filesystem::is_directory(src_root)) {
      pythonpath = src_root.string();
    }

    int to_child[2];
    int from_child[2];
    if (::pipe(to_child) != 0) throw std::runtime_error("pipe() failed: " + StrError());
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
      ::dup2(to_child[0], STDIN_FILENO);
      ::dup2(from_child[1], STDOUT_FILENO);
      ::close(to_child[0]);
      ::close(to_child[1]);
      ::close(from_child[0]);
      ::close(from_child[1]);
      if (!pythonpath.empty()) {
        ::setenv("PYTHONPATH", pythonpath.c_str(), 1);
      }
      const char* argv[] = {python_.c_str(), "-m", "services.inventory.daemon.main", nullptr};
      ::execvp(argv[0], const_cast<char* const*>(argv));
      std::fprintf(stderr, "execvp failed: %s\n", std::strerror(errno));
      std::_Exit(127);
    }

    ::close(to_child[0]);
    ::close(from_child[1]);
    pid_ = child;
    stdin_fd_ = to_child[1];
    stdout_fd_ = from_child[0];
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
      if (n == 0) return std::nullopt;
      if (n < 0) {
        if (errno == EINTR) continue;
        return std::nullopt;
      }
      if (ch == '\n') return out;
      out.push_back(ch);
      if (out.size() > 1024 * 1024) return std::nullopt;
    }
  }
};

struct RouterState {
  std::string active_route;
  bool route_list_cache_complete = false;
  std::vector<std::string> route_list_order;
  bool has_session_active = false;
  json session_active = json::object();
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

std::string ToLowerAscii(std::string s) {
  for (char& c : s) {
    if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
  }
  return s;
}

std::string GetEnvString(const char* key) {
  const char* v = std::getenv(key);
  return v ? std::string(v) : std::string();
}

json ActiveBlockFromEnv() {
  std::string backend = GetEnvString("Z3CLI_BACKEND");
  if (backend.empty()) backend = "studio";
  return json{{"backend", backend},
              {"model", ""},
              {"studio_node", GetEnvString("Z3CLI_STUDIO_NODE")},
              {"llamacpp_node", GetEnvString("Z3CLI_LLAMACPP_NODE")}};
}

json MergeActiveOverlay(json base, const json& overlay) {
  if (!overlay.is_object()) return base;
  for (auto& el : overlay.items()) {
    base[el.key()] = el.value();
  }
  return base;
}

json ActiveBlockForList(const RouterState& state) {
  if (state.has_session_active && state.session_active.is_object() && !state.session_active.empty()) {
    return state.session_active;
  }
  return ActiveBlockFromEnv();
}

json HandleSessionSync(InventorySidecar& inventory, RouterState& state, const json& params) {
  json overlay = json::object();
  if (params.contains("active") && params["active"].is_object()) {
    overlay = params["active"];
  }
  json merged = MergeActiveOverlay(ActiveBlockFromEnv(), overlay);
  state.session_active = std::move(merged);
  state.has_session_active = true;

  if (params.contains("activeRoute") && params["activeRoute"].is_string()) {
    state.active_route = params["activeRoute"].get<std::string>();
  } else if (params.contains("active_route") && params["active_route"].is_string()) {
    state.active_route = params["active_route"].get<std::string>();
  }

  inventory.Request("session/sync", params);
  return json{{"ok", true}};
}

std::string ActiveRouteNameFromEntries(const std::vector<json>& entries,
                                       const std::string& backend,
                                       const std::string& studio_node,
                                       const std::string& llamacpp_node,
                                       const std::string& active_model) {
  const std::string be = ToLowerAscii(backend);
  const std::string studio = ToLowerAscii(studio_node);
  const std::string llama = ToLowerAscii(llamacpp_node);
  const std::string model = ToLowerAscii(active_model);

  for (const auto& entry : entries) {
    if (!entry.is_object()) continue;
    if (ToLowerAscii(entry.value("backend", "")) != be) continue;
    const std::string resolved = ToLowerAscii(entry.value("resolved", ""));
    if (be == "studio" && !studio.empty() && resolved == studio) {
      return entry.value("name", "");
    }
    if (be == "llamacpp" && !llama.empty() && resolved == llama) {
      return entry.value("name", "");
    }
  }
  for (const auto& entry : entries) {
    if (!entry.is_object()) continue;
    if (ToLowerAscii(entry.value("backend", "")) != be) continue;
    if (!model.empty() && ToLowerAscii(entry.value("model", "")) == model) {
      return entry.value("name", "");
    }
  }
  if (be == "studio" && !studio.empty()) return studio;
  if (be == "llamacpp" && !llama.empty()) return llama;
  return active_model;
}

void AugmentActiveBlockFromRoute(json& active, const std::vector<json>& entries, const std::string& route_name) {
  if (route_name.empty()) return;
  const std::string target = ToLowerAscii(route_name);
  for (const auto& entry : entries) {
    if (!entry.is_object()) continue;
    if (ToLowerAscii(entry.value("name", "")) != target) continue;
    if (active.value("model", "").empty()) {
      active["model"] = entry.value("model", "");
    }
    if (active.value("backend", "").empty() || active.value("backend", "") == "studio") {
      active["backend"] = entry.value("backend", active.value("backend", ""));
    }
    const std::string be = ToLowerAscii(entry.value("backend", ""));
    const std::string resolved = entry.value("resolved", "");
    if (be == "studio" && active.value("studio_node", "").empty() && !resolved.empty()) {
      active["studio_node"] = resolved;
    }
    if (be == "llamacpp" && active.value("llamacpp_node", "").empty() && !resolved.empty()) {
      active["llamacpp_node"] = resolved;
    }
    return;
  }
}

json EntryFromSnapshot(const json& snapshot) {
  if (snapshot.contains("routeEntry") && snapshot["routeEntry"].is_object()) {
    json entry = snapshot["routeEntry"];
    if (!entry.contains("kind")) entry["kind"] = "route";
    return entry;
  }
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
  return json{
      {"name", name},
      {"kind", "route"},
      {"backend", backend},
      {"model", model_name},
      {"description", resolved},
      {"resolved", resolved},
      {"aliases", json::array()},
  };
}

json RouteFromSnapshot(const json& snapshot) {
  json route;
  if (snapshot.contains("route") && snapshot["route"].is_object()) {
    route = snapshot["route"];
  } else {
    const std::string name = snapshot.value("source", "");
    const json endpoint = snapshot.value("endpoint", json::object());
    const std::string backend_enum = endpoint.value("backend", "");
    const std::string backend = BackendNameFromEnum(backend_enum);
    route = json{
        {"name", name},
        {"displayName", name},
        {"model", json::object()},
        {"backend", backend_enum.empty() ? "SERVING_BACKEND_UNSPECIFIED" : backend_enum},
        {"inferenceEndpoint", endpoint},
        {"controlEndpoint", json::object()},
        {"aliases", json::array()},
        {"autoLoad", backend == "studio"},
        {"preferred", name == "oracle-pro-5090"},
        {"health", snapshot.value("health", "HEALTH_STATE_UNKNOWN")},
        {"detail", snapshot.value("detail", "")},
        {"generation", snapshot.value("generation", 0)},
    };
  }

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

  if (route.contains("model") && route["model"].is_object() && route["model"].empty() && !model_ref.empty()) {
    route["model"] = model_ref;
  }
  if (route.value("displayName", "").empty() && !display_name.empty()) {
    route["displayName"] = display_name;
  }
  if (!route.contains("toolsEnabled")) route["toolsEnabled"] = tools_enabled;
  if (!route.contains("role")) route["role"] = role;
  if (!route.contains("maxTokens")) route["maxTokens"] = max_tokens;
  route["health"] = snapshot.value("health", route.value("health", "HEALTH_STATE_UNKNOWN"));
  route["detail"] = snapshot.value("detail", route.value("detail", ""));
  route["generation"] = snapshot.value("generation", route.value("generation", 0));
  return route;
}

json HandleRouteList(InventorySidecar& inventory,
                     RouterState& state,
                     std::unordered_map<std::string, CachedSnapshot>& cache) {
  bool cache_ok = state.route_list_cache_complete && !state.route_list_order.empty();
  if (cache_ok) {
    for (const auto& name : state.route_list_order) {
      const auto found = cache.find(name);
      if (found == cache.end() || !SnapshotIsFresh(found->second)) {
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

  json payload;
  payload["active"] = ActiveBlockForList(state);
  payload["entries"] = entries;
  std::string active_route = state.active_route;
  if (active_route.empty()) {
    active_route = ActiveRouteNameFromEntries(entries,
                                              payload["active"].value("backend", ""),
                                              payload["active"].value("studio_node", ""),
                                              payload["active"].value("llamacpp_node", ""),
                                              payload["active"].value("model", ""));
  }
  AugmentActiveBlockFromRoute(payload["active"], entries, active_route);
  if (active_route.empty()) {
    active_route = ActiveRouteNameFromEntries(entries,
                                              payload["active"].value("backend", ""),
                                              payload["active"].value("studio_node", ""),
                                              payload["active"].value("llamacpp_node", ""),
                                              payload["active"].value("model", ""));
  }
  payload["active_route"] = active_route;
  payload["routes"] = routes;
  return payload;
}

json HandleRouteStatus(const RouterState& state, const json& params) {
  const std::string route = params.value("route", "");
  return json{{"route", route.empty() ? state.active_route : route}, {"activeRoute", state.active_route}};
}

json HandleRouteSelect(RouterState& state, const json& params) {
  const std::string route = params.value("route", "");
  if (route.empty()) throw std::runtime_error("route/select requires params.route");
  state.active_route = route;
  return json{{"accepted", true}, {"route", route}, {"message", "Route set to " + route}};
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
      if (method == "session/sync") {
        WriteLine(JsonRpcResult(id, HandleSessionSync(inventory, state, params)));
        continue;
      }
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
        if (!route.empty()) {
          json snapshot = inventory.Request("inventory/refresh", json{{"route", route}});
          const std::string health = snapshot.value("health", "HEALTH_STATE_UNKNOWN");
          CachedSnapshot entry;
          entry.snapshot = snapshot;
          entry.observed = std::chrono::steady_clock::now();
          entry.ttl_ms = snapshot.value("ttlMs", 0);
          entry.generation = snapshot.value("generation", 0);
          snapshot_cache[route] = std::move(entry);
          WriteLine(UiEvent("UI_EVENT_KIND_INVENTORY_UPDATED", request_id, route, "Inventory updated", health, snapshot));
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

