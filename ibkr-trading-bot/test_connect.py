"""Step 3: prove Python can talk to TWS / IB Gateway."""
from ib_async import IB

from src.common import env_int, env_str

ib = IB()
ib.connect(env_str("IBKR_HOST", "127.0.0.1"), env_int("IBKR_PORT", 7497), clientId=99)
print("Connected:", ib.isConnected())
print("Accounts:", ib.managedAccounts())
ib.disconnect()
