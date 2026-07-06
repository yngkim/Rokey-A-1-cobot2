cmake_minimum_required(VERSION 3.8)
project(chess_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(action_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Square.msg"
  "msg/BoardOccupancy.msg"
  "msg/BoardState.msg"
  "msg/ChessMove.msg"
  "msg/GameSnapshot.msg"
  "msg/CoachFeedback.msg"
  "srv/ScanBoard.srv"
  "srv/MoveToObserve.srv"
  "srv/RetreatArm.srv"
  "srv/ResetBoard.srv"
  "srv/ScanInitial.srv"
  "srv/ConfirmPlayerMove.srv"
  "srv/ApplyRobotMove.srv"
  "action/ExecuteMove.action"
  DEPENDENCIES std_msgs action_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
