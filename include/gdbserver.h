#ifndef DOSBOX_GDBSERVER_H
#define DOSBOX_GDBSERVER_H

#include "dosbox.h"

#if C_REMOTEDEBUG

#include <string>
#include <vector>
#include <cstring>
#include <sstream>
#include <iomanip>
#include <atomic>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>

static inline uint32_t swap32(uint32_t x);
static inline uint16_t swap16(uint16_t x);

// GDB command types for thread synchronization
enum class GDBCommand {
    NONE,
    STEP,
    CONTINUE
};

class GDBServer {
public:
    GDBServer(int port) : port(port), server_fd(-1), client_fd(-1), running(false) {}
    ~GDBServer() {
        stop();
    }
    void start();  // Start server in a new thread
    void run();    // Main server loop (called by thread)
    void stop();   // Stop server and wait for thread to exit
    void signal_breakpoint();
    bool is_running() const { return running.load(); }
    bool has_client() const { return client_fd >= 0; }

    // Thread synchronization for step/continue
    // Called by main loop to check if step/continue is pending
    GDBCommand get_pending_command() const { return pending_command.load(); }
    // Called by main loop after executing command
    void complete_command();
    // Check if waiting for command completion
    bool is_waiting() const { return waiting_for_completion.load(); }
    // Check if CPU should be paused (waiting for next GDB command)
    bool is_paused() const { return paused_for_gdb.load(); }
    // Set paused state after step completes
    void set_pause() { paused_for_gdb.store(true); }
    // Clear paused state when a new command arrives
    void clear_pause() { paused_for_gdb.store(false); }

private:
    // Request step/continue and wait for main loop to execute it
    void request_step();
    void request_continue();
    int port;
    int server_fd, client_fd;
    bool noack_mode = false;
    bool processing = false;
    std::atomic<bool> running{false};
    std::thread server_thread;

    // Thread synchronization for step/continue
    std::atomic<GDBCommand> pending_command{GDBCommand::NONE};
    std::atomic<bool> waiting_for_completion{false};
    std::atomic<bool> paused_for_gdb{false};  // CPU paused, waiting for next GDB command
    std::mutex command_mutex;
    std::condition_variable command_cv;

    void setup_socket();
    void wait_for_client();
    void handle_client();
    bool perform_handshake();
    std::string receive_packet();
    void send_packet(const std::string& packet);
    void process_command(const std::string& cmd);

    // GDB command handlers
    void handle_read_register(const std::string& cmd);
    void handle_read_registers();
    void handle_write_registers(const std::string& args);
    void handle_read_memory(const std::string& args);
    void handle_write_memory(const std::string& args);
    void handle_step();
    void handle_continue();
    void handle_breakpoint(const std::string& args);
    void handle_query(const std::string& args);
    void handle_v_packets(const std::string& cmd);

    // Helper functions
    std::string hex_encode(const std::string& input);
    std::string hex_decode(const std::string& input);
    uint8_t hex_to_int(char c);
};

#endif /* C_REMOTEDEBUG */

#endif /* DOSBOX_GDBSERVER_H */
