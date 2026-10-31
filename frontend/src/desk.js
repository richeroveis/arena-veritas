// GenLayer desk wiring. Uses genlayer-js with no local abi override: calls are
// made by function name and decoded by the SDK against the chain schema.
import { createClient } from "genlayer-js";
import { generatePrivateKey } from "viem/accounts";

const ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS;
const CHAIN = "studionet";

export let client = createClient({ chain: CHAIN });
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
  const [avt, refundable, rejection] = await Promise.all([
    read("get_avt_balance", [address]),
    read("get_refundable_balance", [address]),
    read("get_last_payable_rejection", [address]),
  ]);
  return { avt, refundable, rejection };
}

export async function connectBurner() {
  const pk = generatePrivateKey();
  client = createClient({ chain: CHAIN, account: { privateKey: pk } });
  const address = await client.account.getAddress();
  wallet = { address, source: "burner" };
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
