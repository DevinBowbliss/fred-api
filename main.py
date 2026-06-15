import requests
import pyodbc

#connection string for local SQL Server instance with Windows Authentication

CONNECTION_STRING = (
    "Driver={ODBC Driver 17 for SQL Server};"
    "Server=DESKTOP-567UVQM;"
    "Database=Sandbox;"
    "Trusted_Connection=yes;"
)

SERIES_ID  = "LNS14000000"  # US Civilian Unemployment Rate
START_YEAR = 1950
END_YEAR   = 2024

CREATE_TABLE_SQL = """
IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='unemployment' AND xtype='U')
CREATE TABLE unemployment (
    id          INT IDENTITY PRIMARY KEY,
    year        INT  NOT NULL,
    month       INT  NOT NULL,
    period_name NVARCHAR(20),
    value       FLOAT NOT NULL,
    loaded_at   DATETIME2 DEFAULT GETUTCDATE(),
    CONSTRAINT uq_year_month UNIQUE (year, month)
)
"""

UPSERT_SQL = """
MERGE unemployment AS tgt
USING (VALUES (?, ?, ?, ?))
    AS src (year, month, period_name, value)
ON  tgt.year  = src.year
AND tgt.month = src.month
WHEN MATCHED THEN UPDATE SET
    value = src.value
WHEN NOT MATCHED THEN INSERT
    (year, month, period_name, value)
VALUES
    (src.year, src.month, src.period_name, src.value);
"""


def fetch_chunk(start, end):
    url  = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
    body = {"seriesid": [SERIES_ID], "startyear": str(start), "endyear": str(end)}
    resp = requests.post(url, json=body, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    if result["status"] != "REQUEST_SUCCEEDED":
        raise ValueError(f"BLS API error: {result.get('message')}")
    return result["Results"]["series"][0]["data"]


def main():
    all_rows = []

    # BLS limits each request to 10 years, so we loop in chunks
    year = START_YEAR
    while year <= END_YEAR:
        chunk_end = min(year + 9, END_YEAR)
        print(f"Fetching {year} - {chunk_end} ...")
        records = fetch_chunk(year, chunk_end)
        for r in records:
            if r["period"] == "M13":   # skip annual averages
                continue
            all_rows.append((
                int(r["year"]),
                int(r["period"].replace("M", "")),
                r["periodName"],
                float(r["value"]),
            ))
        print(f"  {len(records)} records received.")
        year += 10

    print(f"\nLoading {len(all_rows)} rows into SQL Server ...")

    conn = pyodbc.connect(CONNECTION_STRING)
    try:
        cur = conn.cursor()
        cur.execute(CREATE_TABLE_SQL)
        for row in all_rows:
            cur.execute(UPSERT_SQL, row)
        conn.commit()
        print(f"  Loaded {len(all_rows)} rows into [Sandbox].[dbo].[unemployment].")
    finally:
        conn.close()

    print("\nDone!")


if __name__ == "__main__":
    main()