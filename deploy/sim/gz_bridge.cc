// gz-bridge：进程内 gz-transport 桥（V0.3 W3，2026-09-15）。
//
// 动机（W2 终局定性）：`gz topic` one-shot 发布（每次 subprocess ~0.3s）+
// `gz topic -e` 文本渲染位姿流滞后 ~1s，使任何"发完即睡"控制律过冲/爬行、
// 连续 P 控制发散（15 轮实测，E00174–E00188）。进程内直连 gz-transport 后
// 发布延迟 ~1ms、位姿回调即时送达 stdout。
//
// stdout 行协议（每行即 flush）：
//   R ready                                  就绪（订阅建立）
//   P <name> <x> <y> <z>                     位姿（坐标系语义同 dynamic_pose/info）
//   C <left> <right>                         本条消息两指接触条目数
// stdin：每行 "vx vy vz" → 立即发布 gz.msgs.Twist 到 /model/gripper/cmd_vel
//
// 编译（镜像内）：gcc -x c++ -O2 -std=c++17 gz_bridge.cc -o /usr/local/bin/gz-bridge \
//   $(pkg-config --cflags --libs gz-transport13)
#include <gz/transport/Node.hh>
#include <gz/msgs/twist.pb.h>
#include <gz/msgs/pose_v.pb.h>
#include <gz/msgs/contacts.pb.h>

#include <atomic>
#include <csignal>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>

static std::mutex out_mutex;
static std::atomic<bool> running{true};

static void emit(const std::string &line) {
  std::lock_guard<std::mutex> lk(out_mutex);
  std::cout << line << std::endl;  // endl = flush，控制环依赖行级低延迟
}

static void on_pose(const gz::msgs::Pose_V &msg) {
  for (const auto &p : msg.pose()) {
    std::ostringstream os;
    os << "P " << p.name() << ' ' << p.position().x() << ' '
       << p.position().y() << ' ' << p.position().z();
    emit(os.str());
  }
}

static void on_contacts_left(const gz::msgs::Contacts &msg) {
  emit("C " + std::to_string(msg.contact_size()) + " 0");
}

static void on_contacts_right(const gz::msgs::Contacts &msg) {
  emit("C 0 " + std::to_string(msg.contact_size()));
}

int main(int argc, char **argv) {
  std::signal(SIGINT, SIG_IGN);  // 生命周期由父进程管理（stdin 关闭/terminate）
  std::signal(SIGTERM, [](int) { running = false; });

  const std::string world = argc > 1 ? argv[1] : "bin_picking";

  gz::transport::Node node;
  auto pub = node.Advertise<gz::msgs::Twist>("/model/gripper/cmd_vel");
  node.Subscribe("/world/" + world + "/dynamic_pose/info", on_pose);
  node.Subscribe("/gripper/finger_left/contact", on_contacts_left);
  node.Subscribe("/gripper/finger_right/contact", on_contacts_right);
  emit("R ready");

  std::string line;
  while (running.load() && std::getline(std::cin, line)) {
    std::istringstream is(line);
    double vx = 0, vy = 0, vz = 0;
    if (!(is >> vx >> vy >> vz)) continue;
    gz::msgs::Twist t;
    t.mutable_linear()->set_x(vx);
    t.mutable_linear()->set_y(vy);
    t.mutable_linear()->set_z(vz);
    pub.Publish(t);
  }
  return 0;
}
