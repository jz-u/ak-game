import os, zipfile, textwrap, json
root = "kepler-cannon-variants"
os.makedirs(root, exist_ok=True)

solo_dir = os.path.join(root, "solo-quick-play")
os.makedirs(solo_dir, exist_ok=True)

solo_app = r'''
import os, random, sqlite3
from contextlib import closing
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Truth or Lie — Solo Quick-Play", page_icon="🎭", layout="wide")

ADMIN_PIN = st.secrets.get("ADMIN_PIN", "1234")
DB_PATH = os.environ.get("DB_PATH", "solo.db")

@st.cache_resource
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS players(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE, truth TEXT, lie TEXT,
        score INTEGER DEFAULT 0, played INTEGER DEFAULT 0
    );""")
    conn.execute("""CREATE TABLE IF NOT EXISTS rounds(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER, stmt1 TEXT, stmt2 TEXT, truth_index INTEGER,
        status TEXT DEFAULT 'open'
    );""")
    conn.execute("""CREATE TABLE IF NOT EXISTS votes(
        round_id INTEGER, voter_name TEXT, choice_index INTEGER,
        PRIMARY KEY(round_id, voter_name)
    );""")
    return conn

conn = get_conn()

def q(sql, params=()):
    return pd.read_sql_query(sql, conn, params=params)

def add_player(n,t,l):
    with closing(conn.cursor()) as cur:
        cur.execute("INSERT INTO players(name,truth,lie) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET truth=excluded.truth, lie=excluded.lie;", (n.strip(), t.strip(), l.strip()))
        conn.commit()

def unplayed():
    return q("SELECT * FROM players WHERE played=0 ORDER BY id;")

def mark_played(pid):
    with closing(conn.cursor()) as cur:
        cur.execute("UPDATE players SET played=1 WHERE id=?", (pid,)); conn.commit()

def open_round():
    df = q("SELECT * FROM rounds WHERE status='open' ORDER BY id DESC LIMIT 1;")
    return df.iloc[0] if not df.empty else None

def create_round(player):
    pair=[('T',player['truth']),('L',player['lie'])]; random.shuffle(pair)
    stmt1, stmt2 = pair[0][1], pair[1][1]
    truth_index = 1 if pair[0][0]=='T' else 2
    with closing(conn.cursor()) as cur:
        cur.execute("INSERT INTO rounds(player_id,stmt1,stmt2,truth_index,status) VALUES(?,?,?,?, 'open');",
                    (int(player['id']), stmt1, stmt2, truth_index)); conn.commit()

def cast_vote(rid, voter, choice):
    with closing(conn.cursor()) as cur:
        cur.execute("INSERT OR REPLACE INTO votes(round_id,voter_name,choice_index) VALUES(?,?,?);", (rid, voter.strip(), int(choice))); conn.commit()

def count_votes(rid):
    v = q("SELECT * FROM votes WHERE round_id=?", (rid,))
    total=len(v); c1=int((v['choice_index']==1).sum()); c2=total-c1
    return total,c1,c2

def reveal_and_score(r):
    rid=int(r['id']); truth=int(r['truth_index']); lie=1 if truth==2 else 2
    total,c1,c2 = count_votes(rid)
    fooled_lie = c1 if lie==1 else c2
    fooled_truth = total - (c1 if truth==1 else c2)
    pts = (1 if fooled_lie>0 else 0) + (1 if fooled_truth>0 else 0)
    player = q("SELECT * FROM players WHERE id=?", (int(r['player_id']),)).iloc[0]
    with closing(conn.cursor()) as cur:
        cur.execute("UPDATE players SET score=COALESCE(score,0)+? WHERE id=?", (pts, int(player['id'])))
        cur.execute("UPDATE rounds SET status='revealed' WHERE id=?", (rid,)); conn.commit()
    return pts, truth

st.title("🎭 Truth or Lie — Solo Quick-Play")
tabs = st.tabs(["Submit", "Vote", "Leaderboard", "Host"])

with tabs[0]:
    st.subheader("Submit your 1 Truth + 1 Lie")
    name = st.text_input("Name")
    truth = st.text_area("Truth", height=80)
    lie = st.text_area("Lie", height=80)
    if st.button("Submit / Update"):
        if not (name.strip() and truth.strip() and lie.strip()):
            st.error("Please fill everything.")
        else:
            add_player(name, truth, lie)
            st.success("Saved!")

with tabs[1]:
    st.subheader("Vote: Which one is TRUE?")
    r = open_round()
    if r is None:
        st.info("No active round. Wait for host to start one.")
    else:
        st.write(f"Round #{int(r['id'])}")
        vname = st.text_input("Your display name")
        st.write("1) ", r['stmt1'])
        st.write("2) ", r['stmt2'])
        choice = st.radio("Pick TRUE:", [1,2], horizontal=True, index=0)
        if st.button("Submit / Update Vote"):
            if not vname.strip():
                st.error("Enter your display name.")
            else:
                cast_vote(int(r['id']), vname, int(choice))
                st.success("Vote recorded. You can change it until reveal.")
        total,c1,c2 = count_votes(int(r['id']))
        st.caption(f"Live votes — total: {total} | Option1: {c1} | Option2: {c2}")
        st.autorefresh(3000, key="vote_refresh_solo")

with tabs[2]:
    st.subheader("Leaderboard")
    df = q("SELECT name, score, played FROM players ORDER BY score DESC, id ASC;")
    st.dataframe(df, use_container_width=True)

with tabs[3]:
    st.subheader("Host controls")
    pin = st.text_input("Admin PIN", type="password")
    if pin == ADMIN_PIN:
        r = open_round()
        if r is None:
            up = unplayed()
            if up.empty:
                st.info("All players have played. Use Reset below to run again.")
            else:
                st.write("Players remaining:", len(up))
                st.dataframe(up[['id','name','played']], use_container_width=True, hide_index=True)
                col1,col2 = st.columns(2)
                if col1.button("Start Random Round") and not up.empty:
                    create_round(up.sample(1).iloc[0]); mark_played(int(up.sample(1).iloc[0]['id']))
                    st.rerun()
                pick = col2.selectbox("Start selected:", ["--"] + up['name'].tolist())
                if col2.button("Start Selected") and pick!="--":
                    row = up[up['name']==pick].iloc[0]; create_round(row); mark_played(int(row['id'])); st.rerun()
        else:
            st.warning(f"Round in progress for player_id={int(r['player_id'])}")
            st.write("1) ", r['stmt1']); st.write("2) ", r['stmt2'])
            if st.button("Reveal & Score"):
                pts, truth = reveal_and_score(r)
                st.success(f"Truth was option {truth}. Points awarded: {pts}")
            if st.button("Close Round"):
                with closing(conn.cursor()) as cur:
                    cur.execute("UPDATE rounds SET status='closed' WHERE id=?", (int(r['id']),)); conn.commit()
                st.rerun()
        st.divider()
        if st.button("Reset played flags (keep scores)"):
            with closing(conn.cursor()) as cur:
                cur.execute("UPDATE players SET played=0;"); conn.commit()
            st.success("Reset done.")
        if st.button("Hard reset (clear scores/rounds/votes)"):
            with closing(conn.cursor()) as cur:
                cur.execute("DELETE FROM votes;"); cur.execute("DELETE FROM rounds;"); cur.execute("UPDATE players SET score=0, played=0;"); conn.commit()
            st.error("All data cleared.")
    else:
        st.info("Enter Admin PIN to unlock host controls.")
'''

with open(os.path.join(solo_dir, "app.py"), "w", encoding="utf-8") as f:
    f.write(textwrap.dedent(solo_app))

import runpy, sys
sys.path.insert(0, solo_dir)
runpy.run_path(os.path.join(solo_dir, "app.py"), run_name="__main__")
