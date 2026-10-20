/*  Huroof Cell - Google Apps Script backend
    Deploy: Deploy > New deployment > Web app
    Execute as: Me   |   Who has access: Anyone
    NOTE: this file is pure ASCII on purpose, so no hidden
    right-to-left marks can sneak in when it is copied.        */

function doGet(e) {
  var t = HtmlService.createTemplateFromFile('index');
  // Deployment URL, used to build the QR code
  try { t.webUrl = ScriptApp.getService().getUrl(); } catch (err) { t.webUrl = ''; }
  // Room code arriving from the QR code:  ...exec?r=ABC12
  t.roomParam = (e && e.parameter && e.parameter.r) ? String(e.parameter.r).toUpperCase() : '';
  return t.evaluate()
    .setTitle('\u062e\u0644\u064a\u0629 \u0627\u0644\u062d\u0631\u0648\u0641')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/* ===== JSON API for the GitHub Pages site =====
   The page sends: POST {fn:"getState", args:["ABC12"]}  (Content-Type text/plain)
   and receives:   {result: ...}  or  {error: "..."}                          */

var API_FNS_ = {
  joinRoom: joinRoom, buzz: buzz, getState: getState,
  resetBuzz: resetBuzz, removePlayer: removePlayer,
  setBoard: setBoard, getBoard: getBoard, clearRoom: clearRoom
};

function doPost(e) {
  var out;
  try {
    var req = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    var f = API_FNS_[req.fn];
    if (!f) throw new Error('unknown fn');
    out = { result: f.apply(null, req.args || []) };
  } catch (err) {
    out = { error: String(err && err.message || err) };
  }
  return ContentService.createTextOutput(JSON.stringify(out))
    .setMimeType(ContentService.MimeType.JSON);
}

/* ===== room storage ===== */

var TTL = 21600;  // 6 hours
function cache_() { return CacheService.getScriptCache(); }
function key_(room) { return 'hh_' + String(room || '').toUpperCase(); }

function readRoom_(room) {
  var raw = cache_().get(key_(room));
  if (!raw) return { players: [], order: [], board: null, rev: 0 };
  try { return JSON.parse(raw); }
  catch (err) { return { players: [], order: [], board: null, rev: 0 }; }
}

function writeRoom_(room, data) {
  data.rev = (data.rev || 0) + 1;
  data.ts = Date.now();
  cache_().put(key_(room), JSON.stringify(data), TTL);
  return data;
}

function withLock_(fn) {
  var lock = LockService.getScriptLock();
  try { lock.waitLock(5000); return fn(); }
  finally { try { lock.releaseLock(); } catch (err) {} }
}

/* ===== player side ===== */

function joinRoom(room, name, team) {
  if (!room || !name) return { ok: false, msg: 'missing data' };
  return withLock_(function () {
    var d = readRoom_(room);
    var found = false;
    for (var i = 0; i < d.players.length; i++) {
      if (d.players[i].n === name) { d.players[i].t = team || 1; found = true; break; }
    }
    if (!found) {
      if (d.players.length >= 20) return { ok: false, msg: 'room full' };
      d.players.push({ n: name, t: team || 1 });
    }
    writeRoom_(room, d);
    return { ok: true, players: d.players, order: d.order, rev: d.rev };
  });
}

function buzz(room, name) {
  if (!room || !name) return { ok: false };
  return withLock_(function () {
    var d = readRoom_(room);
    if (d.order.indexOf(name) === -1) d.order.push(name);
    writeRoom_(room, d);
    return { ok: true, order: d.order, rank: d.order.indexOf(name) + 1, rev: d.rev };
  });
}

function getState(room) {
  var d = readRoom_(room);
  return { players: d.players, order: d.order, rev: d.rev || 0 };
}

/* ===== host side ===== */

function resetBuzz(room) {
  return withLock_(function () {
    var d = readRoom_(room);
    d.order = [];
    writeRoom_(room, d);
    return { ok: true, rev: d.rev };
  });
}

function removePlayer(room, name) {
  return withLock_(function () {
    var d = readRoom_(room);
    d.players = d.players.filter(function (p) { return p.n !== name; });
    d.order = d.order.filter(function (n) { return n !== name; });
    writeRoom_(room, d);
    return { ok: true, players: d.players, rev: d.rev };
  });
}

/* Host uploads a board snapshot; requests can arrive out of order,
   so anything older than what is stored is rejected. */
function setBoard(room, snapshot) {
  return withLock_(function () {
    var d = readRoom_(room);
    var oldTs = (d.board && d.board.ts) ? d.board.ts : 0;
    var newTs = (snapshot && snapshot.ts) ? snapshot.ts : 0;
    var oldSeq = (d.board && d.board.seq) ? d.board.seq : 0;
    var newSeq = (snapshot && snapshot.seq) ? snapshot.seq : 0;
    if (newTs && oldTs) {
      if (newTs < oldTs) return { ok: false, stale: true, rev: d.rev || 0 };
      if (newTs === oldTs && newSeq && newSeq < oldSeq) {
        return { ok: false, stale: true, rev: d.rev || 0 };
      }
    }
    d.board = snapshot;
    writeRoom_(room, d);
    return { ok: true, rev: d.rev };
  });
}

function getBoard(room) {
  var d = readRoom_(room);
  return { board: d.board, order: d.order, players: d.players, rev: d.rev || 0 };
}

function clearRoom(room) {
  cache_().remove(key_(room));
  return { ok: true };
}
