import pandas as pd
import matplotlib.pyplot as plt
import glob, re

plt.style.use("seaborn-v0_8")

files = sorted(glob.glob("*.csv"))
print(f"Found {len(files)} CSV files:", *files, sep="\n - ")

def analyze_file(path):
    df = pd.read_csv(path)

    # ✅ Coerce status to STRING so "200" and 200 are treated the same
    status = df["status"].astype(str)

    total   = len(df)
    success = (status == "200").sum()
    timeout = (status.str.lower() == "timeout").sum()
    other   = total - success - timeout

    # Percentiles from successful rows only
    lat_ok = df.loc[status == "200", "latency_ms"]
    if not lat_ok.empty:
        p50, p95, p99 = lat_ok.quantile([0.5, 0.95, 0.99]).astype(int).tolist()
    else:
        p50 = p95 = p99 = None

    return {
        "file": path, "total": total,
        "success": success, "timeout": timeout, "other": other,
        "p50_ms": p50, "p95_ms": p95, "p99_ms": p99,
    }

summary = pd.DataFrame([analyze_file(f) for f in files])

def parse_label(fname):
    backend = "FastAPI" if "fastapi" in fname else ("Flask" if "flask" in fname else "Unknown")
    conc = re.search(r"c(\d+)", fname)
    conc = conc.group(1) if conc else "?"
    cond = "Impaired" if "impair" in fname else "Baseline"
    return f"{backend}-C{conc}-{cond}"

summary["label"] = summary["file"].apply(parse_label)

print("\n=== Summary Results ===")
print(summary[["label","p50_ms","p95_ms","p99_ms","success","timeout","other"]])

summary.to_csv("summary_results.csv", index=False)
print("\n✅ Wrote summary_results.csv")

# Histograms (successful only)
for f in files:
    df = pd.read_csv(f)
    s = df["status"].astype(str)
    lat_ok = df.loc[s == "200", "latency_ms"]
    if not lat_ok.empty:
        plt.hist(lat_ok, bins=40, alpha=0.6, label=f)
plt.xlabel("Latency (ms)"); plt.ylabel("Frequency")
plt.title("Latency distributions (successful requests)")
plt.legend(fontsize=8); plt.savefig("latency_histograms.png", bbox_inches="tight"); plt.close()
print("✅ Wrote latency_histograms.png")

# Tail P99 comparison
for backend in ["FastAPI","Flask"]:
    for cond in ["Baseline","Impaired"]:
        ss = summary[summary["label"].str.contains(backend) & summary["label"].str.contains(cond)]
        if not ss.empty:
            plt.plot(ss["label"], ss["p99_ms"], marker="o", label=f"{backend}-{cond}")
plt.xticks(rotation=45, ha="right")
plt.ylabel("P99 Latency (ms)"); plt.title("Tail latency comparison")
plt.legend(); plt.savefig("tail_latency.png", bbox_inches="tight"); plt.close()
print("✅ Wrote tail_latency.png")

# Success vs timeout bar chart
ax = summary.copy()
ax["success_pct"] = (ax["success"] / ax["total"] * 100).round(1)
ax["timeout_pct"] = (ax["timeout"] / ax["total"] * 100).round(1)
ax[["label","success_pct","timeout_pct"]].set_index("label").plot.bar(figsize=(10,5))
plt.ylabel("Percentage (%)"); plt.title("Success vs Timeout")
plt.tight_layout(); plt.savefig("success_timeout.png"); plt.close()
print("✅ Wrote success_timeout.png")
