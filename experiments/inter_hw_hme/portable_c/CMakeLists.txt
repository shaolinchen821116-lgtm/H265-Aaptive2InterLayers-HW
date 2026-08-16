cmake_minimum_required(VERSION 3.12)
project(hw_hme_reference C)

add_library(hw_hme_reference STATIC hw_hme_reference.c)
target_include_directories(hw_hme_reference PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

add_executable(test_hw_hme test_hw_hme.c)
target_link_libraries(test_hw_hme PRIVATE hw_hme_reference)

enable_testing()
add_test(NAME hw_hme_reference_test COMMAND test_hw_hme)
