cmake_minimum_required(VERSION 3.16)
project(speXtract VERSION 0.1.0 LANGUAGES CXX)

# speXtract is a STANDALONE application that links against an existing OpenMS
# installation. It is deliberately not part of the OpenMS source tree: OpenMS is a
# prerequisite here, not a host.
#
# Point CMake at an OpenMS build or install with:
#   cmake -DOpenMS_DIR=/path/to/OpenMS/build ..

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

find_package(OpenMS REQUIRED)
find_package(OpenMP)

add_executable(DIAPseudoSpectra src/DIAPseudoSpectra.cpp)
target_link_libraries(DIAPseudoSpectra PRIVATE OpenMS)

if(OpenMP_CXX_FOUND)
  # The window/band loop is OpenMP-parallel; without it the tool still builds and runs,
  # but serially -- and the memory-admission logic degrades to one window at a time.
  target_link_libraries(DIAPseudoSpectra PRIVATE OpenMP::OpenMP_CXX)
else()
  message(WARNING "OpenMP not found: DIAPseudoSpectra will run single-threaded.")
endif()

install(TARGETS DIAPseudoSpectra RUNTIME DESTINATION bin)
