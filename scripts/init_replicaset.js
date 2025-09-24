(function () {
  const rsName = (typeof process !== "undefined" && process.env.RS_NAME) || "rs0";
  const membersEnv =
    (typeof process !== "undefined" && process.env.RS_MEMBERS) ||
    "mongo1:27017,mongo2:27017,mongo3:27017";
  const members = membersEnv
    .split(",")
    .map((h) => h.trim())
    .filter(Boolean)
    .map((h, i) => ({ _id: i, host: h }));

  function ok(v) {
    return v && (v.ok === 1 || v.ok === true);
  }

  function waitForPrimary(timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const st = rs.status();
        if (ok(st)) {
          const hasPrimary = (st.members || []).some((m) => m.stateStr === "PRIMARY");
          if (hasPrimary) return true;
        }
      } catch (e) {}
      sleep(1000);
    }
    return false;
  }

  function printStatus() {
    try {
      const st = rs.status();
      printjsononeline({
        set: st.set,
        ok: st.ok,
        myState: st.myState,
        members: (st.members || []).map((m) => ({
          name: m.name,
          state: m.state,
          stateStr: m.stateStr,
          health: m.health,
        })),
      });
    } catch (e) {
      printjsononeline({ ok: 0, error: e.message || e.toString() });
    }
  }

  try {
    let initiated = false;
    try {
      const st = rs.status();
      if (ok(st)) {
        if (st.set && st.set !== rsName) {
          printjsononeline({
            note: "replica set already initialized with different name",
            currentSet: st.set,
            expectedSet: rsName,
          });
        }
        initiated = true;
      }
    } catch (e) {
      initiated = false;
    }

    if (!initiated) {
      const cfg = { _id: rsName, members: members };
      const res = rs.initiate(cfg);
      if (!ok(res)) {
        printjsononeline({ ok: 0, error: "rs.initiate failed", res: res });
        printStatus();
        quit(1);
      }
    }

    if (!waitForPrimary(60_000)) {
      printjsononeline({ ok: 0, error: "primary did not become available within timeout" });
      printStatus();
      quit(1);
    }

    printStatus();
    quit(0);
  } catch (e) {
    printjsononeline({ ok: 0, error: e.message || e.toString() });
    quit(1);
  }
})();
