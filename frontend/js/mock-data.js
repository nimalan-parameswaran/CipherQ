// CipherQ Mock Data Layer for Phase 1 UI Verification
// Simulates two users (Free vs Premium) and encrypted file operations

export const MOCK_USERS = {
  free: {
    id: "usr_free_01",
    email: "maya.freelancer@example.com",
    name: "Maya Chen",
    plan_type: "FREE",
    storage_bytes_used: 340 * 1024 * 1024, // 340 MB
    storage_quota_bytes: 1 * 1024 * 1024 * 1024, // 1 GB
    ai_queries_today: 0,
    ai_daily_limit: 0
  },
  premium: {
    id: "usr_prem_02",
    email: "alex.researcher@example.com",
    name: "Alex Vance",
    plan_type: "PREMIUM",
    storage_bytes_used: 1.85 * 1024 * 1024 * 1024, // 1.85 GB
    storage_quota_bytes: 5 * 1024 * 1024 * 1024, // 5 GB
    ai_queries_today: 14,
    ai_daily_limit: 100
  }
};

export const MOCK_FILES = [
  {
    id: "fil_9a8b7c01",
    user_id: "usr_free_01",
    original_name: "Client_Consulting_Agreement_2026.pdf",
    file_size_bytes: 2457600, // 2.34 MB
    mime_type: "application/pdf",
    sha256_hash: "3e23e8160039594a33894f6564e1b1348bbd7a0088d42c4acb73eeaed59c009d",
    is_indexed: false,
    status: "ACTIVE",
    created_at: "2026-10-15T10:30:00Z"
  },
  {
    id: "fil_9a8b7c02",
    user_id: "usr_free_01",
    original_name: "Tax_Receipts_Q3.txt",
    file_size_bytes: 143360, // 140 KB
    mime_type: "text/plain",
    sha256_hash: "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
    is_indexed: false,
    status: "ACTIVE",
    created_at: "2026-10-16T14:15:00Z"
  },
  {
    id: "fil_1f2e3d01",
    user_id: "usr_prem_02",
    original_name: "Arduino_UNO_Q_Architecture_Notes.pdf",
    file_size_bytes: 4194304, // 4.00 MB
    mime_type: "application/pdf",
    sha256_hash: "fbc0e99e0cf4fc00438b4f0b263363065b263901b2024da832ef653556771d9d",
    is_indexed: true,
    status: "ACTIVE",
    created_at: "2026-10-12T09:00:00Z"
  },
  {
    id: "fil_1f2e3d02",
    user_id: "usr_prem_02",
    original_name: "Debian_Embedded_Kernel_Profiling.txt",
    file_size_bytes: 524288, // 512 KB
    mime_type: "text/plain",
    sha256_hash: "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
    is_indexed: true,
    status: "ACTIVE",
    created_at: "2026-10-14T16:20:00Z"
  }
];

export const MOCK_AI_RESPONSES = [
  {
    query: "What is the memory budget for the embedded Linux board?",
    answer: "Based on your indexed document 'Arduino_UNO_Q_Architecture_Notes.pdf', the board is equipped with 4GB RAM and 32GB eMMC storage. The system reserves approximately 500MB for Debian Linux and background daemons, leaving up to 2.5GB for user operations and bounded local inference.",
    sources: [
      { filename: "Arduino_UNO_Q_Architecture_Notes.pdf", page: 2, chunk_id: "chk_001" }
    ],
    mode: "SEMANTIC_LOCAL"
  },
  {
    query: "What kernel tuning was applied for streaming I/O?",
    answer: "According to 'Debian_Embedded_Kernel_Profiling.txt', read-ahead buffers were set to 128KB and dirty writeback ratios were lowered to prevent burst stalling during continuous 64KB AES-GCM chunk writes.",
    sources: [
      { filename: "Debian_Embedded_Kernel_Profiling.txt", line: 45, chunk_id: "chk_004" }
    ],
    mode: "KEYWORD_FTS5"
  }
];
