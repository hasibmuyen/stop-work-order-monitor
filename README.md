# stop-work-order-monitor

This application polls the [NSW Register of building work orders](https://www.nsw.gov.au/departments-and-agencies/building-commission/register-of-building-work-orders) for Stop Work Orders, reads the licence number or ACN from the PDF under **Resource downloads**, and stores each new order in SQL Server. It emails a notification when an order is recorded.

A company is stored once. A builder licence number identifies it when the PDF prints one. Otherwise the Australian Company Number (ACN) identifies it. `company_number_type` records which of those numbers is being used: `licence`, `acn`, or `unstated`. The same company can have a separate Stop Work Order for each site address. An order is not stored again when that company number and site address have already been recorded.

## Main Python libraries used
httpx - for making html requests and receiving response
beautifulsoup4 - for parsing html
pypdf - read pdf
sqlalchemy - ORM
smtplib - sending email

## What is stored

| Field | Source |
| --- | --- |
| Company name | Order title (`Stop Work Order for …`) |
| Company address | Registered address in the PDF letterhead |
| Company number | Licence number (`Lic. No`) if present; otherwise the 9-digit `ACN` / `A.C.N` |
| Company number type | `licence`, `acn`, or `unstated`; identifies the kind of value in `company_number` |
| Site address | Register summary for that order |
| Date added | Register publication date |

The notification contains the company name, the company number, the company number type, and the date the Stop Work Order was added.

The individual Stop Work Orders are stored in table `stop_work_orders`

## Configuration

Non-secret settings, with a comment on every key, are in [config/settings.yaml](config/settings.yaml).

Secrets come from the environment. Copy [.env.example](.env.example) to `.env` and set:

- `SQLSERVER_USER` - username for the login. It is inserted into the connection string as `UID=`. Replace the placeholder in `.env`
- `SQLSERVER_PASSWORD` — password for the username login. It is inserted into the connection string as `PWD=`. Replace the placeholder in `.env`.
- `SMTP_PASSWORD` — required when `smtp.enabled` is true and `smtp.username` is set

Optional environment overrides are listed in `.env.example`. They replace the matching keys in the YAML file. Do not put passwords in the YAML file.

## Database

The application connects to `<host>` as `SQLSERVER_USER`, with `SQLSERVER_PASSWORD` from `.env` inserted into the connection string. 
The server name is configurable in `settings.yaml` under `host`.
On startup it creates `StopWorkOrders` if that database does not exist, then creates `dbo.companies` and `dbo.stop_work_orders` if those tables do not exist.

[scripts/init_db.sql](scripts/init_db.sql) is the schema source. A manual run is only needed when you want to prepare the database yourself:

```text
sqlcmd -S "<host>" -U "<SQLSERVER_USER>" -P "<SQLSERVER_PASSWORD>" -C -i scripts/init_db.sql
```

If you change `sqlserver.database`, edit the `CREATE DATABASE` and `USE` batches before running the script by hand. The application creates the database named in configuration and then applies the table batches.

## Run

Install Python 3.11 or newer and [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server). LocalDB must be available as `(localdb)\MSSQLLocalDB`. Then:

```text
python -m pip install -r requirements.txt
python -m pip install -e .
copy .env.example .env
python -m stop_work_monitor --once
```

`pip install -e .` puts the `src` package on Python's import path. Without that step, `python -m stop_work_monitor` reports `No module named stop_work_monitor`.

Omit `--once` to keep polling every `poll_interval_minutes`.

## Deployment package

`scripts/build-deployment-package.ps1` writes `dist/stop-work-order-monitor/` with the application, configuration, schema script, and a `wheels` folder of the pinned Python dependencies. Install those wheels with:

```text
python -m pip install --no-index --find-links=wheels -r requirements.txt
```

## Setting up local smtp server for testing
Mailpit is used to run local smtp server
Install mailpit in windows powershell
```
winget install -e --id axllent.mailpit
```

To run the mail server run in powershell
```
mailpit
```

The emails sent can be seen in the following url
```
http://localhost:8025
```

## Tests

```text
python -m pip install -r requirements-dev.txt
python -m pytest
```
