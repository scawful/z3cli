cmake_minimum_required(VERSION 3.24)

project(z3cli_daemons LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)

# JSON parsing for NDJSON JSON-RPC.
FetchContent_Declare(
  nlohmann_json
  GIT_REPOSITORY https://github.com/nlohmann/json.git
  GIT_TAG v3.11.3
)
FetchContent_MakeAvailable(nlohmann_json)

add_executable(z3cli-routerd
  routerd/main.cc
)

target_link_libraries(z3cli-routerd PRIVATE nlohmann_json::nlohmann_json)
