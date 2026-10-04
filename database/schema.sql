-- Schema for pharmacy.db: the three cleaned source tables plus the denormalised fact_orders mart.
-- Timestamps are stored as TEXT in '%Y-%m-%d %H:%M:%S' so SQLite's datetime() and strftime() work on them.
-- Every row originates from database/generate_data.py under a fixed seed.

DROP TABLE IF EXISTS fact_orders;
DROP TABLE IF EXISTS deliveries;
DROP TABLE IF EXISTS prescription_verification;
DROP TABLE IF EXISTS orders;

CREATE TABLE orders (
    Order_ID                 TEXT    PRIMARY KEY,
    Customer_ID              TEXT    NOT NULL,
    Order_Date               TEXT    NOT NULL,
    -- 'Unknown' is the DQ-04 fallback when no source city could be inferred; its tier is NULL.
    Customer_City            TEXT    NOT NULL,
    City_Tier                TEXT    CHECK (City_Tier IN ('Tier 1', 'Tier 2')),
    Medicine_Category        TEXT    NOT NULL CHECK (Medicine_Category IN ('Chronic', 'OTC')),
    Is_Prescription_Required INTEGER NOT NULL CHECK (Is_Prescription_Required IN (0, 1)),
    Order_Value              REAL    NOT NULL CHECK (Order_Value > 0),
    Shipping_Fee             REAL    NOT NULL CHECK (Shipping_Fee >= 0),
    Order_Status             TEXT    NOT NULL CHECK (Order_Status IN ('Completed', 'Cancelled', 'Refunded')),
    CHECK ((Customer_City = 'Unknown') = (City_Tier IS NULL))
);

CREATE TABLE prescription_verification (
    Order_ID                          TEXT PRIMARY KEY REFERENCES orders (Order_ID),
    Prescription_Submitted_Time       TEXT,
    Prescription_Verified_Time        TEXT,
    Prescription_Status               TEXT NOT NULL
        CHECK (Prescription_Status IN ('Approved', 'Rejected', 'Pending', 'Not Required')),
    Prescription_Verification_Minutes REAL CHECK (Prescription_Verification_Minutes >= 0),
    -- Non-Rx orders carry a row so the join stays 1:1, but no times and no minutes (DQ-07).
    CHECK (Prescription_Status <> 'Not Required'
           OR (Prescription_Submitted_Time IS NULL AND Prescription_Verification_Minutes IS NULL)),
    -- Pending means never verified; DQ-06 nulls any verified time that precedes submission.
    CHECK (Prescription_Verified_Time IS NULL
           OR Prescription_Verified_Time >= Prescription_Submitted_Time)
);

CREATE TABLE deliveries (
    Order_ID                TEXT    PRIMARY KEY REFERENCES orders (Order_ID),
    Delivery_Partner        TEXT    NOT NULL,
    Promised_Delivery_Hours INTEGER NOT NULL CHECK (Promised_Delivery_Hours IN (24, 48, 72)),
    -- NULL for In Transit and Returned parcels, and wherever DQ-05/DQ-10 removed an unusable duration.
    Actual_Delivery_Hours   REAL    CHECK (Actual_Delivery_Hours BETWEEN 0 AND 500),
    Delivery_Status         TEXT    NOT NULL CHECK (Delivery_Status IN ('Delivered', 'In Transit', 'Returned')),
    Refund_Amount           REAL    NOT NULL CHECK (Refund_Amount >= 0),
    Refund_Flag             INTEGER NOT NULL CHECK (Refund_Flag IN (0, 1)),
    CHECK ((Refund_Flag = 1) = (Refund_Amount > 0))
);

-- One row per clean order; orders excluded by DQ-02/DQ-03 never reach this table.
-- Populated by sql/07_business_summary.sql and exported as the Power BI and Excel source.
CREATE TABLE fact_orders (
    Order_ID                 TEXT    PRIMARY KEY REFERENCES orders (Order_ID),
    Customer_ID              TEXT    NOT NULL,
    Order_Date               TEXT    NOT NULL,
    Order_Month              TEXT    NOT NULL,
    Customer_City            TEXT    NOT NULL,
    City_Tier                TEXT    CHECK (City_Tier IN ('Tier 1', 'Tier 2')),
    Medicine_Category        TEXT    NOT NULL CHECK (Medicine_Category IN ('Chronic', 'OTC')),
    Is_Prescription_Required INTEGER NOT NULL CHECK (Is_Prescription_Required IN (0, 1)),
    Order_Value              REAL    NOT NULL,
    Shipping_Fee             REAL    NOT NULL,
    Order_Status             TEXT    NOT NULL CHECK (Order_Status IN ('Completed', 'Cancelled', 'Refunded')),
    Prescription_Status      TEXT    NOT NULL,
    Verification_Minutes     REAL,
    Verification_Bucket      TEXT    NOT NULL
        CHECK (Verification_Bucket IN ('0-30', '31-60', '61-120', '>120', 'Not Required', 'Unknown')),
    Delivery_Partner         TEXT,
    Promised_Delivery_Hours  REAL,
    Actual_Delivery_Hours    REAL,
    Delivery_Status          TEXT,
    Refund_Flag              INTEGER NOT NULL CHECK (Refund_Flag IN (0, 1)),
    Refund_Amount            REAL    NOT NULL CHECK (Refund_Amount >= 0),
    Is_Delivered             INTEGER NOT NULL CHECK (Is_Delivered IN (0, 1)),
    -- Canonical denominator for On-Time Delivery Rate and SLA Breach Rate.
    Is_Sla_Eligible          INTEGER NOT NULL CHECK (Is_Sla_Eligible IN (0, 1)),
    Is_On_Time               INTEGER CHECK (Is_On_Time IN (0, 1)),
    Is_Late                  INTEGER CHECK (Is_Late IN (0, 1)),
    -- Actual minus promised; negative means early. Avg Delay (Late Only) must filter Is_Late = 1 before averaging.
    Delay_Hours              REAL,
    CHECK ((Verification_Bucket = 'Not Required') = (Is_Prescription_Required = 0)),
    CHECK (Is_Sla_Eligible = 0 OR (Is_Delivered = 1 AND Actual_Delivery_Hours IS NOT NULL)),
    CHECK (CASE WHEN Is_Sla_Eligible = 1
                THEN Is_On_Time IS NOT NULL AND Is_Late = 1 - Is_On_Time
                ELSE Is_On_Time IS NULL AND Is_Late IS NULL END)
);

CREATE INDEX idx_orders_city ON orders (Customer_City);
CREATE INDEX idx_orders_status ON orders (Order_Status);
CREATE INDEX idx_orders_date ON orders (Order_Date);
CREATE INDEX idx_orders_category ON orders (Medicine_Category, Is_Prescription_Required);
CREATE INDEX idx_rx_status ON prescription_verification (Prescription_Status);
CREATE INDEX idx_deliveries_partner ON deliveries (Delivery_Partner);
CREATE INDEX idx_deliveries_status ON deliveries (Delivery_Status);
CREATE INDEX idx_fact_city_partner ON fact_orders (Customer_City, Delivery_Partner);
CREATE INDEX idx_fact_month ON fact_orders (Order_Month);
CREATE INDEX idx_fact_bucket ON fact_orders (Verification_Bucket);
CREATE INDEX idx_fact_sla ON fact_orders (Is_Sla_Eligible, Is_On_Time);
