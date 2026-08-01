"""
Faym.co PM Intern Assignment - Part A: Wallet Transactions Data Case Study
--------------------------------------------------------------------------
Reproduces every answer in the submission document by running the actual
SQL queries against the provided dataset and generating the bell curve /
box plot.

Usage:
    pip install pandas matplotlib
    python analysis.py

Inputs:
    dataset.csv  - the cleaned dataset (extracted from Data Set (2).pdf)

Outputs (printed to stdout + written to disk):
    Q1 - 7th highest IMPS debit
    Q2 - category-wise transaction counts
    Q3 - statistical summary + bellcurve_boxplot.png
    Q4 - monthly cohort matrix of active debit users
    Q5 - top 10-percentile users by net amount (DEBIT - CREDIT)
"""

import sqlite3
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


CSV_PATH = "dataset.csv"
CHART_PATH = "bellcurve_boxplot.png"


def load_data():
    df = pd.read_csv(CSV_PATH)
    df["Transaction Time"] = pd.to_datetime(df["Transaction Time"])
    conn = sqlite3.connect(":memory:")
    df.to_sql("transactions", conn, if_exists="replace", index=False)
    return df, conn


def q1_seventh_highest_imps_debit(conn):
    print("\n===== Q1: 7th highest debit amount through IMPS =====")
    sql = """
        SELECT "Transaction Amt" AS debit_amount,
               "User Id", Txn_id, "Transaction Time"
        FROM transactions
        WHERE Narration = 'IMPS' AND "Transaction Type" = 'DEBIT'
        ORDER BY "Transaction Amt" DESC
        LIMIT 1 OFFSET 6;
    """
    print(sql.strip())
    result = pd.read_sql(sql, conn)
    print("\nResult:")
    print(result.to_string(index=False))
    print("\nTop 10 IMPS debits (context):")
    top = pd.read_sql(
        """SELECT "Transaction Amt", "User Id", Txn_id, "Transaction Time"
           FROM transactions
           WHERE Narration = 'IMPS' AND "Transaction Type" = 'DEBIT'
           ORDER BY "Transaction Amt" DESC LIMIT 10""",
        conn,
    )
    print(top.to_string(index=False))


def q2_category_wise_counts(conn):
    print("\n===== Q2: Number of transactions category-wise =====")
    sql = """
        SELECT Narration AS Category, COUNT(*) AS Num_Txns
        FROM transactions
        GROUP BY Narration
        ORDER BY Num_Txns DESC;
    """
    print(sql.strip())
    result = pd.read_sql(sql, conn)
    result["pct"] = (result["Num_Txns"] / result["Num_Txns"].sum() * 100).round(1)
    print("\nResult:")
    print(result.to_string(index=False))


def q3_stats_and_chart(df):
    print("\n===== Q3: Bell curve, box plot, statistical summary =====")
    amt = df["Transaction Amt"]
    stats = {
        "count": int(amt.count()),
        "mean": round(amt.mean(), 2),
        "median": round(amt.median(), 2),
        "std": round(amt.std(), 2),
        "min": int(amt.min()),
        "q1": int(amt.quantile(0.25)),
        "q3": int(amt.quantile(0.75)),
        "max": int(amt.max()),
        "iqr": int(amt.quantile(0.75) - amt.quantile(0.25)),
        "skew": round(amt.skew(), 3),
        "kurtosis_excess": round(amt.kurt(), 3),
    }
    print("\nStatistical summary:")
    for k, v in stats.items():
        print(f"  {k:>18}: {v}")

    mu, sigma = amt.mean(), amt.std()
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].hist(amt, bins=30, density=True, color="#4C72B0",
                 alpha=0.7, edgecolor="white")
    x = np.linspace(amt.min(), amt.max(), 200)
    normal_pdf = (1 / (sigma * np.sqrt(2 * np.pi))) * \
                 np.exp(-0.5 * ((x - mu) / sigma) ** 2)
    axes[0].plot(x, normal_pdf, color="red", linewidth=2,
                 label=f"Normal fit (μ={mu:.0f}, σ={sigma:.0f})")
    axes[0].set_title("Distribution of Transaction (Load) Amount")
    axes[0].set_xlabel("Transaction Amount")
    axes[0].set_ylabel("Density")
    axes[0].legend()
    axes[1].boxplot(amt, vert=True, patch_artist=True,
                    boxprops=dict(facecolor="#4C72B0", alpha=0.7),
                    medianprops=dict(color="red", linewidth=2))
    axes[1].set_title("Box Plot of Transaction (Load) Amount")
    axes[1].set_ylabel("Transaction Amount")
    axes[1].set_xticklabels(["All Transactions"])
    plt.tight_layout()
    plt.savefig(CHART_PATH, dpi=150)
    print(f"\nChart saved to: {CHART_PATH}")


def q4_cohort(df):
    print("\n===== Q4: Monthly cohort of active debit users =====")
    debit = df[df["Transaction Type"] == "DEBIT"].copy()
    first_month = debit.groupby("User Id")["Month"].min().rename("cohort_month")
    debit = debit.merge(first_month, on="User Id")
    months = sorted(df["Month"].unique())
    cohort_months = sorted(first_month.unique())
    matrix = (
        debit.groupby(["cohort_month", "Month"])["User Id"]
        .nunique()
        .unstack(fill_value=0)
        .reindex(index=cohort_months, columns=months, fill_value=0)
    )
    print("\nCohort matrix (# distinct active debit users):")
    print(matrix)
    print("\nCohort sizes (users whose first-ever DEBIT was in month M):")
    print(first_month.value_counts().sort_index().to_string())


def q5_top_10_percentile(conn):
    print("\n===== Q5: Top 10-percentile users by net amount =====")
    sql = """
        WITH user_net AS (
            SELECT "User Id",
                SUM(CASE WHEN "Transaction Type" = 'DEBIT'  THEN "Transaction Amt" ELSE 0 END) -
                SUM(CASE WHEN "Transaction Type" = 'CREDIT' THEN "Transaction Amt" ELSE 0 END)
                AS net_amount
            FROM transactions
            GROUP BY "User Id"
        )
        SELECT "User Id", net_amount
        FROM user_net
        ORDER BY net_amount DESC;
    """
    print(sql.strip())
    result = pd.read_sql(sql, conn)
    print("\nFull ranking:")
    print(result.to_string(index=False))
    cutoff = result["net_amount"].quantile(0.90)
    top10 = result[result["net_amount"] >= cutoff]
    print(f"\n90th percentile cutoff (net_amount): {cutoff}")
    print("Top 10-percentile users:")
    print(top10.to_string(index=False))


def main():
    df, conn = load_data()
    print(f"Loaded {len(df)} transactions across {df['User Id'].nunique()} users, "
          f"{df['Narration'].nunique()} rails.")
    q1_seventh_highest_imps_debit(conn)
    q2_category_wise_counts(conn)
    q3_stats_and_chart(df)
    q4_cohort(df)
    q5_top_10_percentile(conn)


if __name__ == "__main__":
    main()
