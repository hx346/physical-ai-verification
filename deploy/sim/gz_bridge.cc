// gz-bridge：进程内 gz-transport 桥（V0.3 W3，2026-09-15；V0.5 W3 扩深度捕获）。
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
//   D_OK <w> <h>                             深度帧已落盘（V0.5 W3 感知链）
//   D_ERR <reason>                           深度捕获失败（subscribe/timeout/write）
// stdin：
//   每行 "vx vy vz"      → 立即发布 gz.msgs.Twist 到 /model/gripper/cmd_vel
//   "D <topic> <path>"   → 订阅深度话题，捕获一帧 float32 原始数据写 <path>，
//                          回 D_OK/D_ERR 后退订。帧 ~3.7MB（1280×720×4）走文件
//                          不走 stdout（行协议会被撑爆）
//
// 编译（镜像内）：gcc -x c++ -O2 -std=c++17 gz_bridge.cc -o /usr/local/bin/gz-bridge \
//   $(pkg-config --cflags --libs gz-transport13)
#include <gz/transport/Node.hh>
#include <gz/msgs/twist.pb.h>
#include <gz/msgs/pose_v.pb.h>
#include <gz/msgs/contacts.pb.h>
#include <gz/msgs/image.pb.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <fstream>
#include <future>
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

// 单帧深度捕获（V0.5 W3）：订阅→等一帧→原始字节落盘→退订。
// gz-transport13 的 Subscribe 只收函数指针（无捕获可转换）——promise 用
// 文件级静态传递；桥按 stdin 命令串行处理，同一时刻仅一个捕获，安全。
static std::promise<gz::msgs::Image> g_depth_promise;
static std::atomic<bool> g_depth_got{false};

static void on_depth_frame(const gz::msgs::Image &msg) {
  if (!g_depth_got.exchange(true)) {
    g_depth_promise.set_value(msg);
  }
}

static bool capture_depth(gz::transport::Node &node, const std::string &topic,
                          const std::string &path) {
  g_depth_got = false;
  g_depth_promise = std::promise<gz::msgs::Image>();
  auto future = g_depth_promise.get_future();
  if (!node.Subscribe(topic, on_depth_frame)) {
    emit("D_ERR subscribe");
    return false;
  }
  bool ok = false;
  if (future.wait_for(std::chrono::seconds(4)) ==
      std::future_status::ready) {
    const auto msg = future.get();
    if (msg.width() > 0 && msg.height() > 0 && !msg.data().empty()) {
      std::ofstream f(path, std::ios::binary | std::ios::trunc);
      f.write(msg.data().data(), static_cast<std::streamsize>(msg.data().size()));
      f.flush();
      if (f.good()) {
        emit("D_OK " + std::to_string(msg.width()) + " " +
             std::to_string(msg.height()));
        ok = true;
      } else {
        emit("D_ERR write");
      }
    } else {
      emit("D_ERR empty_frame");
    }
  } else {
    emit("D_ERR timeout");
  }
  node.Unsubscribe(topic);
  return ok;
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
    if (line.rfind("D ", 0) == 0) {  // D <topic> <path>
      std::istringstream is(line);
      std::string tag, topic, path;
      is >> tag >> topic >> path;
      if (!topic.empty() && !path.empty()) {
        capture_depth(node, topic, path);
      } else {
        emit("D_ERR args");
      }
      continue;
    }
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
