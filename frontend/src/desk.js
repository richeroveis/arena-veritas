// GenLayer desk wiring. Uses genlayer-js with no local abi override: calls are
// made by function name and decoded by the SDK against the chain schema.
import { createAccount, createClient, generatePrivateKey } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { CalldataAddress } from "genlayer-calldata";

const ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS;

// GenVM Address parameters are their own calldata type: 20 raw bytes wrapped by
// the SDK class. A plain hex string is encoded as text and the chain reverts,
// so every address argument goes through this helper.
export function addrArg(address) {
  const hex = String(address).replace(/^0x/, "").toLowerCase();
  if (!/^[0-9a-f]{40}$/.test(hex)) throw new Error("not an address: " + address);
  const bytes = new Uint8Array(20);
  for (let i = 0; i < 20; i += 1) bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return new CalldataAddress(bytes);
}

export let client = createClient({ chain: studionet });
export let wallet = null; // { address, source: "burner" | "metamask" }

// Initial page load budget: 2 RPC calls (leaderboard + custody summary).
export async function loadDeskSnapshot() {
  const [leaderboard, summary] = await Promise.all([
    client.readContract({ address: ADDRESS, functionName: "get_tournament_leaderboard", args: [] }),
    client.readContract({ address: ADDRESS, functionName: "get_custody_accounting_summary", args: [] }),
  ]);
  return { leaderboard, summary };
}

export async function read(method, args = []) {
  return client.readContract({ address: ADDRESS, functionName: method, args });
}

export async function loadWalletLedger(address) {
  const holder = addrArg(address);
  const [avt, refundable, rejection] = await Promise.all([
    read("get_avt_balance", [holder]),
    read("get_refundable_balance", [holder]),
    read("get_last_payable_rejection", [holder]),
  ]);
  return { avt, refundable, rejection };
}

export async function connectBurner() {
  // A fresh in-memory competitor wallet. The key never leaves this tab and is
  // never written to storage, so it cannot be reused after a reload.
  const account = createAccount(generatePrivateKey());
  client = createClient({ chain: studionet, account });
  wallet = { address: account.address, source: "burner" };
  return wallet;
}

export async function connectMetaMask() {
  if (!window.ethereum) throw new Error("MetaMask not detected");
  const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
  wallet = { address: accounts[0], source: "metamask" };
  return wallet;
}

export async function act(method, args = [], value = 0n, wait = false) {
  if (!wallet) throw new Error("connect a wallet first");
  if (wallet.source === "metamask") {
    throw new Error("MetaMask is read-only on this desk; use the burner competitor wallet to sign");
  }
  const hash = await client.writeContract({
    address: ADDRESS, functionName: method, args, value,
  });
  if (wait) {
    const receipt = await client.waitForTransactionReceipt({ hash });
    return { hash, status: receipt?.status_name ?? receipt?.status };
  }
  return { hash };
}

export const contractAddress = ADDRESS;
