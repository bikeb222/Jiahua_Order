IF OBJECT_ID(N'dbo.web_order_draft_lines', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.web_order_draft_lines
    (
        id int IDENTITY(1,1) NOT NULL CONSTRAINT PK_web_order_draft_lines PRIMARY KEY,
        draft_id int NOT NULL,
        line_no int NOT NULL,
        product_code varchar(50) NOT NULL,
        description varchar(255) NULL,
        warehouse varchar(10) NULL,
        pack decimal(18,4) NULL,
        tax_ind varchar(10) NULL,
        order_qty decimal(18,4) NOT NULL,
        unit_name varchar(20) NULL,
        shipped_qty decimal(18,4) NOT NULL CONSTRAINT DF_web_order_draft_lines_shipped_qty DEFAULT (0),
        unit_price decimal(18,4) NOT NULL,
        ext_amount decimal(18,4) NOT NULL,
        available_qty decimal(18,4) NULL,
        ship_date date NULL,
        created_at datetime2(0) NOT NULL CONSTRAINT DF_web_order_draft_lines_created_at DEFAULT (sysdatetime())
    );
END;

IF OBJECT_ID(N'dbo.web_order_drafts', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.web_order_drafts
    (
        id int IDENTITY(1,1) NOT NULL CONSTRAINT PK_web_order_drafts PRIMARY KEY,
        draft_no AS ('WEB-' + RIGHT('000000' + CONVERT(varchar(20), id), 6)) PERSISTED,
        so_number int NULL,
        status varchar(20) NOT NULL CONSTRAINT DF_web_order_drafts_status DEFAULT ('draft'),
        customer_id varchar(50) NULL,
        customer_name varchar(120) NULL,
        phone varchar(40) NULL,
        order_date date NOT NULL,
        ship_date date NULL,
        order_type varchar(120) NULL,
        ship_via varchar(120) NULL,
        sales_one varchar(20) NULL,
        sales_two varchar(20) NULL,
        warehouse varchar(10) NULL,
        po_number varchar(80) NULL,
        ref_number varchar(80) NULL,
        attention varchar(120) NULL,
        bill_name varchar(120) NULL,
        bill_address varchar(255) NULL,
        bill_city varchar(80) NULL,
        bill_state varchar(40) NULL,
        bill_zip varchar(30) NULL,
        ship_name varchar(120) NULL,
        ship_address varchar(255) NULL,
        ship_city varchar(80) NULL,
        ship_state varchar(40) NULL,
        ship_zip varchar(30) NULL,
        terms varchar(80) NULL,
        terms_days decimal(18,4) NULL,
        terms_cod varchar(10) NULL,
        email varchar(120) NULL,
        subtotal decimal(18,4) NOT NULL,
        taxable_amount decimal(18,4) NOT NULL,
        tax_rate decimal(18,4) NOT NULL,
        tax_amount decimal(18,4) NOT NULL,
        discount decimal(18,4) NOT NULL,
        handling decimal(18,4) NOT NULL,
        total decimal(18,4) NOT NULL,
        source varchar(40) NOT NULL CONSTRAINT DF_web_order_drafts_source DEFAULT ('web-prototype'),
        created_at datetime2(0) NOT NULL CONSTRAINT DF_web_order_drafts_created_at DEFAULT (sysdatetime()),
        updated_at datetime2(0) NOT NULL CONSTRAINT DF_web_order_drafts_updated_at DEFAULT (sysdatetime())
    );

    ALTER TABLE dbo.web_order_draft_lines
        ADD CONSTRAINT FK_web_order_draft_lines_draft
        FOREIGN KEY (draft_id) REFERENCES dbo.web_order_drafts(id);
END;

IF COL_LENGTH('dbo.web_order_drafts', 'so_number') IS NULL
BEGIN
    ALTER TABLE dbo.web_order_drafts ADD so_number int NULL;
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.web_order_drafts')
      AND name = N'UX_web_order_drafts_so_number'
)
BEGIN
    EXEC(N'
        CREATE UNIQUE INDEX UX_web_order_drafts_so_number
            ON dbo.web_order_drafts(so_number)
            WHERE so_number IS NOT NULL;
    ');
END;
