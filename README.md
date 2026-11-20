# VirtualPay

VirtualPay is a Streamlit prototype for organizing one bank balance into purpose-based virtual account budgets. Virtual accounts are allocations in the app; money is not moved into separate bank accounts.

## Run locally

1. Install Python 3.10 or newer.
2. From this folder, install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Start the app:

   ```bash
   streamlit run app.py
   ```

The app opens in your browser, usually at `http://localhost:8501`.

## Demo sign-in

- Enter any 10-digit phone number.
- Use OTP `123456`.
- Demo Admin profile: phone `1223334444`, PIN `282005`; its main account has unlimited simulated funds.
- New users can create a demo profile, choose a sample bank, enter an optional starting demo balance (defaults to ₹0), and set a made-up payment PIN.
- Returning users enter the same phone number and their demo PIN.

New profiles start with one main account, no virtual accounts, and an empty activity history. Users create and fund virtual accounts themselves.

QR codes and camera scanning are for VirtualPay demo IDs. The camera stays off until the user chooses **Open camera to scan QR**; the browser then requests camera permission. Transfers are simulated; the app does not connect to a bank, send UPI payments, or require a real PIN. Account and transaction data is stored locally in `virtualpay.db`.

## App flow

- Sign in with a phone number and demo OTP. New profiles get a main account only; the starting demo balance defaults to ₹0, and virtual-account history starts empty.
- The home screen shows the profile, VirtualPay ID and QR, plus Account, Transfer money, History, and Scan QR actions.
- The Account page starts with two choices: Main account and Create virtual account. Each asks for the demo PIN before showing the main-account balance or opening the creation form. Afterward, manage virtual accounts by adding, withdrawing, or moving allocations with PIN confirmation.
- Transfers support saved recipients, a recipient name and ID, a chosen source account, and demo PIN confirmation. The camera scanner opens only after an explicit scan action.

## Backend and user data

The backend is implemented in Python in `app.py`, alongside the Streamlit interface. It handles demo sign-in, account allocation and rebalancing, simulated transfers, QR creation and scanning, and transaction history. SQLite queries and business logic are kept in the same file; this prototype does not use a separate API server.

The database is created automatically at `virtualpay.db` in the project folder when the app starts. A newly registered profile starts with no virtual accounts, transactions, or saved recipients. The main-account demo balance defaults to zero. The database stores:

- User profile details: phone number, name, selected bank, and the last four account digits
- A hash of the demo payment PIN
- Virtual account names, budgets, and allocated balances
- Transaction history and saved recipients

The database is listed in `.gitignore`, so it is not committed to or uploaded to GitHub. Data stays on the machine running Streamlit. If the app is deployed, the database will be on that server instead. This local SQLite setup is for prototyping; it is not designed as secure production banking storage.

## Project files

- `app.py` — Streamlit UI and local SQLite demo logic
- `requirements.txt` — Python dependencies
- `.streamlit/config.toml` — Streamlit's native theme settings
