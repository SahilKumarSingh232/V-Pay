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
- New users can create a demo profile, choose a sample bank, and set a made-up payment PIN.
- Returning users enter the same phone number and their demo PIN.

QR codes and camera scanning are for VirtualPay demo IDs. Transfers are simulated; the app does not connect to a bank, send UPI payments, or require a real PIN. Account and transaction data is stored locally in `virtualpay.db`.

## Project files

- `app.py` — Streamlit UI and local SQLite demo logic
- `requirements.txt` — Python dependencies
- `.streamlit/config.toml` — Streamlit's native theme settings
