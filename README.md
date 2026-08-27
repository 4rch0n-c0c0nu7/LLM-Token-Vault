LLM Token Vault & Routing HUD 🛡️An encrypted, lightweight API key manager and multi-provider routing dashboard designed for edge computing, cyberdecks, and local AI projects.Created by 4rch0n-c0c0nu7.

The ProblemMost open-source AI projects tell you to paste your highly sensitive API keys into a plaintext .env file. If you are building on portable hardware (like a Raspberry Pi cyberdeck) and your device is lost or stolen, your API keys are compromised instantly. 

Furthermore, enterprise-grade LLM routers usually require heavy Docker containers, PostgreSQL databases, and Redis caches—which is massive overkill for a local maker project.💡 

The SolutionThis project provides a scalpel instead of a sledgehammer. 

It features a pure-Python, lightweight Tkinter HUD that routes your prompts across multiple providers (Groq, Gemini, Cerebras, etc.) while keeping your API keys locked inside a hardware-tied AES-256 encrypted vault.Key FeaturesHardware-Locked Encryption: Uses cryptography.fernet and PBKDF2HMAC to encrypt your keys. 

The decryption key is derived using a salt and your specific system's hardware ID (/etc/machine-id on Linux, falling back to UUID on Mac/Windows). If the keys file is stolen and moved to another computer, it cannot be decrypted.Live Token Telemetry: The GUI pings active providers and visualizes your rate limits and available tokens.Multi-Provider Support: Seamlessly handles Groq, Google Gemini, OpenRouter, OpenAI, Cerebras, Mistral, and local Ollama.Lightweight: No heavy server stacks required. Perfect for Raspberry Pi 5.🚀 Installation & SetupClone the repository:git clone https://github.com/4rch0n-c0c0nu7/LLM-Token-Vault.git
cd LLM-Token-Vault

