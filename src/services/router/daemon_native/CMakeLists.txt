cmake_minimum_required(VERSION 3.24)

project(z3cli_routerd LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_executable(z3cli-routerd
  main.cc
)

target_include_directories(z3cli-routerd PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/include")

