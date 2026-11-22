-- Schema for the Stop Work Order monitor.
--
-- Manual setup against the default database name:
--   sqlcmd -S <host> -U "<SQLSERVER_USER>" -P "<SQLSERVER_PASSWORD>" -C -i scripts/init_db.sql
--
-- The application also runs the table batches in this file on startup.
-- It creates sqlserver.database from config/settings.yaml first, then skips
-- the CREATE DATABASE and USE batches below. Keep the table definitions here
-- as the single schema source.
--
-- A company is unique by licence number when the PDF states one, otherwise by
-- ACN. company_number_type records which number identifies the company:
-- licence, acn, or unstated. A company can have one Stop Work Order for each
-- site address. An order with neither number is unique by its register URL.

IF DB_ID(N'StopWorkOrders') IS NULL
BEGIN
    CREATE DATABASE [StopWorkOrders];
END
GO

USE [StopWorkOrders];
GO

IF OBJECT_ID(N'dbo.companies', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.companies (
        id INT IDENTITY(1, 1) NOT NULL,
        -- SHA-256 of the typed company number, otherwise the company name.
        company_key CHAR(64) NOT NULL,
        -- Licence number or nine-digit ACN, as indicated by company_number_type.
        company_number NVARCHAR(50) NULL,
        -- Type of company_number: licence, acn, or unstated.
        company_number_type NVARCHAR(20) NOT NULL,
        -- Company or individual named on the Stop Work Order.
        company_name NVARCHAR(300) NOT NULL,
        -- Registered address from the PDF letterhead, not the work site.
        company_address NVARCHAR(500) NULL,
        -- Publication date of the earliest Stop Work Order recorded for this company.
        -- The public register does not publish a separate liquidation-list date.
        liquidation_list_added_on DATE NOT NULL,
        created_at DATETIME2 NOT NULL CONSTRAINT df_companies_created_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_companies PRIMARY KEY (id),
        CONSTRAINT uq_companies_company_key UNIQUE (company_key),
        CONSTRAINT ck_companies_number_type
            CHECK (company_number_type IN (N'licence', N'acn', N'unstated'))
    );
END
GO

IF OBJECT_ID(N'dbo.stop_work_orders', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.stop_work_orders (
        id INT IDENTITY(1, 1) NOT NULL,
        company_id INT NOT NULL,
        -- Development / site address the order applies to.
        site_address NVARCHAR(500) NOT NULL,
        order_title NVARCHAR(500) NOT NULL,
        source_url NVARCHAR(1000) NOT NULL,
        -- SHA-256 of source_url. Indexed because the URL itself is too long for a unique key.
        source_url_hash CHAR(64) NOT NULL,
        -- SHA-256 of licence|site, otherwise ACN|site, otherwise the source URL.
        dedup_key CHAR(64) NOT NULL,
        -- SHA-256 of company name|normalised site address. Collapses a later notice for the same site.
        site_key CHAR(64) NOT NULL,
        source_nid INT NULL,
        pdf_url NVARCHAR(1000) NULL,
        -- Date the order was added to the public register.
        order_added_on DATE NOT NULL,
        notification_sent BIT NOT NULL CONSTRAINT df_stop_work_orders_notification_sent DEFAULT 0,
        notification_sent_at DATETIME2 NULL,
        notification_error NVARCHAR(1000) NULL,
        created_at DATETIME2 NOT NULL CONSTRAINT df_stop_work_orders_created_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_stop_work_orders PRIMARY KEY (id),
        CONSTRAINT fk_stop_work_orders_company
            FOREIGN KEY (company_id) REFERENCES dbo.companies (id),
        CONSTRAINT uq_stop_work_orders_source_url_hash UNIQUE (source_url_hash),
        CONSTRAINT uq_stop_work_orders_dedup_key UNIQUE (dedup_key),
        CONSTRAINT uq_stop_work_orders_site_key UNIQUE (site_key)
    );
END
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = N'ix_stop_work_orders_notification_sent'
      AND object_id = OBJECT_ID(N'dbo.stop_work_orders')
)
BEGIN
    CREATE INDEX ix_stop_work_orders_notification_sent
        ON dbo.stop_work_orders (notification_sent)
        WHERE notification_sent = 0;
END
GO
