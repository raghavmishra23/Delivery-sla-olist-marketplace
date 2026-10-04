-- Schema for olist.db: the cleaned source tables plus the denormalised fact_orders mart.
-- Timestamps are TEXT in '%Y-%m-%d %H:%M:%S' so SQLite's DATE(), DATETIME() and JULIANDAY() work on them.
--
-- THE ON-TIME DEFINITION. order_estimated_delivery_date is stored at 00:00:00 on every row, so the promise
-- is a calendar day, not an instant. On-time is therefore DATE(Delivered_Ts) <= DATE(Estimated_Ts).
-- Comparing the raw timestamps instead marks 1,292 orders delivered during their promised day as late and
-- moves the headline rate by 1.34 points. Durations below are the opposite: they are timestamp differences
-- in hours, deliberately finer than the date-level promise. Do not mix the two.
--
-- Duration decomposition, all measured in hours from the purchase timestamp except Transit_Hours:
--   Approval_Hours  = approved  - purchase      payment approval lag
--   Handoff_Hours   = carrier   - purchase      time to the carrier handoff (contains the approval lag)
--   Transit_Hours   = delivered - carrier       carrier transit
--   Handoff_Hours + Transit_Hours = Actual_Delivery_Hours
-- Any lag a DQ rule disowned is NULL here; the order itself is never dropped for it.

DROP TABLE IF EXISTS fact_orders;
DROP TABLE IF EXISTS order_reviews;
DROP TABLE IF EXISTS order_payments;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS geolocation;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS sellers;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    Customer_ID         TEXT PRIMARY KEY,
    Customer_Unique_Id  TEXT NOT NULL,
    Customer_Zip_Prefix TEXT NOT NULL,
    Customer_City       TEXT NOT NULL,
    Customer_State      TEXT NOT NULL
);

CREATE TABLE sellers (
    Seller_Id         TEXT PRIMARY KEY,
    Seller_Zip_Prefix TEXT NOT NULL,
    Seller_City       TEXT NOT NULL,
    Seller_State      TEXT NOT NULL
);

CREATE TABLE products (
    Product_Id          TEXT PRIMARY KEY,
    Product_Category_Pt TEXT,
    -- NULL where the product carries no category, or where the translation table has no entry for it.
    Product_Category    TEXT
);

CREATE TABLE geolocation (
    Zip_Prefix TEXT PRIMARY KEY,
    Geo_Lat    REAL NOT NULL,
    Geo_Lng    REAL NOT NULL,
    Geo_City   TEXT NOT NULL,
    Geo_State  TEXT NOT NULL
);

CREATE TABLE orders (
    Order_ID                TEXT PRIMARY KEY,
    Customer_ID             TEXT NOT NULL REFERENCES customers (Customer_ID),
    Order_Status            TEXT NOT NULL,
    Purchase_Ts             TEXT NOT NULL,
    Approved_Ts             TEXT,
    Carrier_Ts              TEXT,
    Delivered_Ts            TEXT,
    Estimated_Ts            TEXT NOT NULL,
    Approval_Hours          REAL CHECK (Approval_Hours >= 0),
    Handoff_Hours           REAL CHECK (Handoff_Hours >= 0),
    Transit_Hours           REAL CHECK (Transit_Hours >= 0),
    Actual_Delivery_Hours   REAL CHECK (Actual_Delivery_Hours >= 0),
    Promised_Delivery_Hours REAL CHECK (Promised_Delivery_Hours >= 0),
    -- Signed: negative means the parcel arrived before the promised date.
    Delay_Hours             REAL,
    Approval_Bucket         TEXT NOT NULL
        CHECK (Approval_Bucket IN ('0-1h', '1-6h', '6-24h', '>24h', 'Unknown')),
    Is_Delivered            INTEGER NOT NULL CHECK (Is_Delivered IN (0, 1)),
    Is_Sla_Eligible         INTEGER NOT NULL CHECK (Is_Sla_Eligible IN (0, 1)),
    Is_On_Time              INTEGER CHECK (Is_On_Time IN (0, 1)),
    Is_Late                 INTEGER CHECK (Is_Late IN (0, 1)),
    CHECK ((Approval_Bucket = 'Unknown') = (Approval_Hours IS NULL)),
    CHECK (Is_Sla_Eligible = 0 OR (Is_Delivered = 1 AND Delivered_Ts IS NOT NULL)),
    CHECK (CASE WHEN Is_Sla_Eligible = 1
                THEN Is_On_Time IS NOT NULL AND Is_Late = 1 - Is_On_Time
                ELSE Is_On_Time IS NULL AND Is_Late IS NULL END)
);

CREATE TABLE order_items (
    Order_ID          TEXT NOT NULL REFERENCES orders (Order_ID),
    Order_Item_Id     INTEGER NOT NULL,
    Product_Id        TEXT NOT NULL REFERENCES products (Product_Id),
    Seller_Id         TEXT NOT NULL REFERENCES sellers (Seller_Id),
    Shipping_Limit_Ts TEXT,
    Price             REAL NOT NULL CHECK (Price >= 0),
    Freight_Value     REAL NOT NULL CHECK (Freight_Value >= 0),
    -- Exactly one item per order carries the flag: the highest-priced one, ties broken on item number.
    -- It is what resolves seller attribution on the multi-seller orders logged under DQ-13.
    Is_Primary_Item   INTEGER NOT NULL CHECK (Is_Primary_Item IN (0, 1)),
    PRIMARY KEY (Order_ID, Order_Item_Id)
);

CREATE TABLE order_payments (
    Order_ID             TEXT NOT NULL REFERENCES orders (Order_ID),
    Payment_Sequential   INTEGER NOT NULL,
    Payment_Type         TEXT NOT NULL,
    Payment_Installments INTEGER NOT NULL CHECK (Payment_Installments >= 0),
    Payment_Value        REAL NOT NULL CHECK (Payment_Value >= 0),
    -- One flagged row per order: the largest payment value, ties broken on sequence number (DQ-12).
    Is_Primary_Payment   INTEGER NOT NULL CHECK (Is_Primary_Payment IN (0, 1)),
    PRIMARY KEY (Order_ID, Payment_Sequential)
);

CREATE TABLE order_reviews (
    Order_ID         TEXT PRIMARY KEY REFERENCES orders (Order_ID),
    Review_Id        TEXT NOT NULL,
    Review_Score     INTEGER NOT NULL CHECK (Review_Score BETWEEN 1 AND 5),
    Review_Created_Ts TEXT,
    Review_Answer_Ts  TEXT
);

-- One row per order. Populated by sql/07_business_summary.sql and exported to
-- data/processed/fact_orders.csv as the dashboard, Excel and Power BI source.
-- Item_Count, Seller_Count, Order_Value, Freight_Value and the seller and category columns are NULL on the
-- orders that have no order_items row (DQ-04); Review_Score and Is_Low_Review are NULL where no review exists.
CREATE TABLE fact_orders (
    Order_ID                TEXT PRIMARY KEY REFERENCES orders (Order_ID),
    Customer_ID             TEXT NOT NULL,
    Customer_City           TEXT NOT NULL,
    Customer_State          TEXT NOT NULL,
    Order_Status            TEXT NOT NULL,
    Purchase_Ts             TEXT NOT NULL,
    Order_Month             TEXT NOT NULL,
    Approved_Ts             TEXT,
    Carrier_Ts              TEXT,
    Delivered_Ts            TEXT,
    Estimated_Ts            TEXT NOT NULL,
    Approval_Hours          REAL,
    Handoff_Hours           REAL,
    Transit_Hours           REAL,
    Actual_Delivery_Hours   REAL,
    Promised_Delivery_Hours REAL,
    Delay_Hours             REAL,
    Approval_Bucket         TEXT NOT NULL
        CHECK (Approval_Bucket IN ('0-1h', '1-6h', '6-24h', '>24h', 'Unknown')),
    Is_Delivered            INTEGER NOT NULL CHECK (Is_Delivered IN (0, 1)),
    -- Canonical denominator for On-Time Rate and SLA Breach Rate.
    Is_Sla_Eligible         INTEGER NOT NULL CHECK (Is_Sla_Eligible IN (0, 1)),
    Is_On_Time              INTEGER CHECK (Is_On_Time IN (0, 1)),
    Is_Late                 INTEGER CHECK (Is_Late IN (0, 1)),
    Item_Count              INTEGER CHECK (Item_Count > 0),
    Seller_Count            INTEGER CHECK (Seller_Count > 0),
    Primary_Seller_Id       TEXT,
    Seller_State            TEXT,
    Product_Category        TEXT,
    Order_Value             REAL CHECK (Order_Value >= 0),
    Freight_Value           REAL CHECK (Freight_Value >= 0),
    Payment_Type            TEXT,
    Payment_Installments    INTEGER,
    Review_Score            INTEGER CHECK (Review_Score BETWEEN 1 AND 5),
    Is_Low_Review           INTEGER CHECK (Is_Low_Review IN (0, 1)),
    CHECK ((Approval_Bucket = 'Unknown') = (Approval_Hours IS NULL)),
    CHECK (Is_Sla_Eligible = 0 OR (Is_Delivered = 1 AND Delivered_Ts IS NOT NULL)),
    CHECK (CASE WHEN Is_Sla_Eligible = 1
                THEN Is_On_Time IS NOT NULL AND Is_Late = 1 - Is_On_Time
                ELSE Is_On_Time IS NULL AND Is_Late IS NULL END),
    -- Low review is defined on the score, so the two are present or absent together.
    CHECK ((Review_Score IS NULL) = (Is_Low_Review IS NULL)),
    CHECK (Is_Low_Review IS NULL OR Is_Low_Review = (Review_Score <= 2)),
    CHECK ((Item_Count IS NULL) = (Seller_Count IS NULL))
);

CREATE INDEX idx_orders_status ON orders (Order_Status);
CREATE INDEX idx_orders_customer ON orders (Customer_ID);
CREATE INDEX idx_orders_purchase ON orders (Purchase_Ts);
CREATE INDEX idx_orders_sla ON orders (Is_Sla_Eligible, Is_On_Time);
CREATE INDEX idx_items_seller ON order_items (Seller_Id);
CREATE INDEX idx_items_product ON order_items (Product_Id);
CREATE INDEX idx_items_primary ON order_items (Order_ID, Is_Primary_Item);
CREATE INDEX idx_payments_primary ON order_payments (Order_ID, Is_Primary_Payment);
CREATE INDEX idx_customers_state ON customers (Customer_State);
CREATE INDEX idx_sellers_state ON sellers (Seller_State);
CREATE INDEX idx_fact_state ON fact_orders (Customer_State);
CREATE INDEX idx_fact_seller ON fact_orders (Primary_Seller_Id);
CREATE INDEX idx_fact_month ON fact_orders (Order_Month);
CREATE INDEX idx_fact_category ON fact_orders (Product_Category);
CREATE INDEX idx_fact_bucket ON fact_orders (Approval_Bucket);
CREATE INDEX idx_fact_sla ON fact_orders (Is_Sla_Eligible, Is_On_Time);
