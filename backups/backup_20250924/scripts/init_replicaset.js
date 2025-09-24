(function () {
  const env = (typeof process !== "undefined" && process.env) || {};
  const setName = env.MONGO_RS_NAME || "rs0";
  const membersEnv = env.MONGO_RS_MEMBERS || "mongodb:27017";
  const preferredPrimary = env.MONGO_RS_PRIMARY || membersEnv.split(",")[0].trim();

  function uniq(arr) {
    const s = new Set();
    const out = [];
    for (const v of arr) {
      const x = v.trim();
      if (!x) continue;
      if (!s.has(x)) {
        s.add(x);
        out.push(x);
      }
    }
    return out;
  }

  const desiredMembers = uniq(membersEnv.split(","));
  if (!desiredMembers.length) {
    print("ERROR: No members defined (MONGO_RS_MEMBERS).");
    quit(2);
  }

  function buildConfig() {
    return {
      _id: setName,
      members: desiredMembers.map((host, i) => ({
        _id: i,
        host,
        priority: host === preferredPrimary ? 2 : 1,
      })),
    };
  }

  function sleep(ms) {
    const end = Date.now() + ms;
    while (Date.now() < end) {}
  }

  function waitPrimary(timeoutMs) {
    const until = Date.now() + timeoutMs;
    while (Date.now() < until) {
      try {
        const st = rs.status();
        if (st.ok === 1) {
          if (st.myState === 1) return true;
          const m = (st.members || []).find((x) => x.stateStr === "PRIMARY");
          if (m) return true;
        }
      } catch (e) {}
      sleep(500);
    }
    return false;
  }

  function notInitializedError(e) {
    const msg = String(e || "");
    return (
      /not yet initialized/i.test(msg) ||
      /no replset config has been received/i.test(msg) ||
      /not initialized/i.test(msg)
    );
  }

  function ensureInitiated() {
    try {
      rs.status();
      return;
    } catch (e) {
      if (!notInitializedError(e)) {
        print("ERROR: rs.status() failed:");
        print(e);
        quit(3);
      }
    }
    const cfg = buildConfig();
    printjson({ action: "initiate", setName, members: desiredMembers });
    const res = rs.initiate(cfg);
    printjson(res);
    waitPrimary(30000);
  }

  function ensureMembers() {
    let conf;
    try {
      conf = rs.conf();
    } catch (e) {
      print("ERROR: rs.conf() failed:");
      print(e);
      quit(4);
    }
    const existingHosts = new Set(conf.members.map((m) => m.host));
    let changed = false;

    for (const host of desiredMembers) {
      if (!existingHosts.has(host)) {
        printjson({ action: "add", host });
        const r = rs.add(host);
        printjson(r);
        changed = true;
      }
    }

    // Align priorities for preferred primary; keep others at 1
    for (const m of conf.members) {
      const want = m.host === preferredPrimary ? 2 : 1;
      if (m.priority !== want) {
        m.priority = want;
        changed = true;
      }
    }

    if (changed) {
      conf.version = (conf.version || 1) + 1;
      printjson({ action: "reconfig", setName, version: conf.version });
      try {
        printjson(rs.reconfig(conf, { force: true }));
      } catch (e) {
        print("WARN: reconfig(force) failed, retrying without force");
        try {
          printjson(rs.reconfig(conf));
        } catch (e2) {
          print("ERROR: reconfig failed");
          print(e2);
          quit(5);
        }
      }
      waitPrimary(30000);
    } else {
      print("INFO: Replica set already up-to-date.");
    }
  }

  function summary() {
    try {
      const st = rs.status();
      printjson({
        ok: st.ok,
        set: st.set,
        myState: st.myState,
        primary:
          (st.members || []).find((m) => m.stateStr === "PRIMARY")?.name || null,
      });
    } catch (e) {
      print("ERROR: final rs.status() failed:");
      print(e);
      quit(6);
    }
  }

  printjson({ setName, desiredMembers, preferredPrimary });
  ensureInitiated();
  ensureMembers();
  summary();
})();
