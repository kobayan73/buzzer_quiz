const { WebSocketServer } = require("ws");

const port = 8787;
const server = new WebSocketServer({ port });

server.on("connection", (socket) => {
  socket.on("message", (message) => {
    socket.send(message);
  });
});

server.on("listening", () => {
  console.log(`WebSocket latency server running on ws://localhost:${port}`);
});

server.on("error", (error) => {
  console.error("WebSocket latency server error:", error);
});
