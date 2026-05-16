const http = require("http");
const { WebSocketServer } = require("ws");

const PORT = Number(process.env.PORT || 8788);
const HOST = "0.0.0.0";
const collectWindowMs = 160;
const rooms = new Map();

function getRoom(roomCode) {
  if (!rooms.has(roomCode)) {
    rooms.set(roomCode, {
      clients: new Map(),
      buzzesByQuestion: new Map(),
      winnerIssuedByQuestion: new Set(),
      collectTimers: new Map(),
      finished: false
    });
  }
  return rooms.get(roomCode);
}

function safeJson(value) {
  try {
    return JSON.parse(value.toString());
  } catch (error) {
    return null;
  }
}

function send(socket, message) {
  if (socket.readyState === socket.OPEN) {
    socket.send(JSON.stringify(message));
  }
}

function broadcast(roomCode, message) {
  const room = rooms.get(roomCode);
  if (!room) return;

  const withRoom = {
    roomCode,
    serverSentAt: new Date().toISOString(),
    ...message
  };

  room.clients.forEach((client) => send(client.socket, withRoom));
}

function roomMembers(roomCode) {
  const room = rooms.get(roomCode);
  if (!room) return [];
  return Array.from(room.clients.values()).map(({ playerId, role, label }) => ({
    playerId,
    role,
    label
  }));
}

function displayTime(localReactionMs) {
  return Number.isFinite(localReactionMs) && localReactionMs >= 0
    ? `${(localReactionMs / 1000).toFixed(3)}s`
    : "";
}

function localReaction(message) {
  const value = Number(message.localReactionMs ?? message.reactionMs);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function issueBuzzWinner(roomCode, questionIndex) {
  const room = rooms.get(roomCode);
  if (!room || room.winnerIssuedByQuestion.has(questionIndex)) return;

  const buzzes = (room.buzzesByQuestion.get(questionIndex) || []).slice();
  if (buzzes.length === 0) return;

  buzzes.sort((a, b) => {
    const ar = localReaction(a);
    const br = localReaction(b);
    if (ar !== null && br !== null && ar !== br) return ar - br;
    if (ar !== null && br === null) return -1;
    if (ar === null && br !== null) return 1;
    return a.serverReceivedAtMs - b.serverReceivedAtMs;
  });

  const winner = buzzes[0];
  const winnerReactionMs = localReaction(winner);

  room.winnerIssuedByQuestion.add(questionIndex);
  room.collectTimers.delete(questionIndex);

  broadcast(roomCode, {
    type: "buzz_winner",
    questionIndex,
    timingBasis: "local_reaction_ms",
    winnerPlayerId: winner.playerId,
    winnerRole: winner.role,
    winnerLabel: winner.label,
    winnerReactionMs,
    winnerDisplayTime: displayTime(winnerReactionMs),
    serverReceivedAt: winner.serverReceivedAt,
    buzzes: buzzes.map((buzz) => {
      const reactionMs = localReaction(buzz);
      return {
        playerId: buzz.playerId,
        role: buzz.role,
        label: buzz.label,
        localReactionMs: reactionMs,
        displayTime: displayTime(reactionMs),
        serverReceivedAt: buzz.serverReceivedAt
      };
    })
  });
}

function resetBuzzStateForQuestion(roomCode, questionIndex) {
  const room = rooms.get(roomCode);
  if (!room || !Number.isFinite(questionIndex)) return;

  const timer = room.collectTimers.get(questionIndex);
  if (timer) clearTimeout(timer);

  room.collectTimers.delete(questionIndex);
  room.buzzesByQuestion.delete(questionIndex);
  room.winnerIssuedByQuestion.delete(questionIndex);

  console.log(`[ws] buzz state reset for ${roomCode} q${questionIndex}`);
}

function handleBuzz(socket, message) {
  const roomCode = message.roomCode;
  const questionIndex = Number(message.questionIndex);
  if (!roomCode || !Number.isFinite(questionIndex)) return;

  const room = getRoom(roomCode);
  if (room.winnerIssuedByQuestion.has(questionIndex)) return;

  const serverReceivedAt = new Date().toISOString();
  const buzz = {
    ...message,
    questionIndex,
    serverReceivedAt,
    serverReceivedAtMs: Date.now()
  };

  if (!room.buzzesByQuestion.has(questionIndex)) {
    room.buzzesByQuestion.set(questionIndex, []);
  }

  const existing = room.buzzesByQuestion
    .get(questionIndex)
    .find((item) => item.playerId === buzz.playerId && item.label === buzz.label);
  if (existing) return;

  room.buzzesByQuestion.get(questionIndex).push(buzz);

  if (!room.collectTimers.has(questionIndex)) {
    const timer = setTimeout(() => {
      issueBuzzWinner(roomCode, questionIndex);
    }, collectWindowMs);
    room.collectTimers.set(questionIndex, timer);
  }
}

function handleJoin(socket, message) {
  const { roomCode, playerId, role, label } = message;
  if (!roomCode || !playerId) return;

  const room = getRoom(roomCode);
  socket.roomCode = roomCode;
  socket.playerId = playerId;

  room.clients.set(playerId, {
    socket,
    playerId,
    role,
    label
  });

  broadcast(roomCode, {
    type: "room_members",
    members: roomMembers(roomCode)
  });
}

function handleForward(message) {
  const roomCode = message.roomCode;
  if (!roomCode) return;

  if (message.type === "judgement" && message.correct === false) {
    resetBuzzStateForQuestion(roomCode, Number(message.questionIndex));
  }

  if (message.type === "next_question") {
    resetBuzzStateForQuestion(roomCode, Number(message.questionIndex));
  }

  broadcast(roomCode, {
    ...message,
    serverReceivedAt: new Date().toISOString()
  });
}

const server = http.createServer((req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true }));
    return;
  }

  res.writeHead(200, { "content-type": "text/plain; charset=utf-8" });
  res.end("Buzzer Quiz WebSocket game server\n");
});

const wss = new WebSocketServer({ server });

wss.on("connection", (socket) => {
  socket.on("message", (raw) => {
    const message = safeJson(raw);
    if (!message || !message.type) return;

    if (message.type === "join_room") {
      handleJoin(socket, message);
      return;
    }

    if (message.type === "buzz") {
      handleBuzz(socket, message);
      return;
    }

    if (message.type === "answer" || message.type === "judgement" || message.type === "next_question") {
      handleForward(message);
      return;
    }

    if (message.type === "finish_match") {
      const room = getRoom(message.roomCode);
      room.finished = true;
      handleForward(message);
      return;
    }

    if (message.type === "leave_room") {
      socket.close();
      return;
    }

    if (message.type === "ping") {
      send(socket, { type: "pong", serverReceivedAt: new Date().toISOString() });
    }
  });

  socket.on("close", () => {
    if (!socket.roomCode || !socket.playerId) return;
    const room = rooms.get(socket.roomCode);
    if (!room) return;
    room.clients.delete(socket.playerId);
    broadcast(socket.roomCode, {
      type: "room_members",
      members: roomMembers(socket.roomCode)
    });
  });
});

wss.on("error", (error) => {
  console.error("WebSocket game server error:", error);
});

server.listen(PORT, HOST, () => {
  console.log(`WebSocket game server listening on ${PORT}`);
  console.log(`Local WebSocket URL: ws://localhost:${PORT}`);
});

server.on("error", (error) => {
  console.error("HTTP/WebSocket server error:", error);
});
