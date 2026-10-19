window.CIPHERQ_API_BASE_URL = ""; // Leave empty for local development (relative path /api/v1)

window.PLANS_CONFIG = {
  free: {
    id: 'free',
    name: 'Free',
    price: '₹0',
    period: '',
    storage: '1 GB',
    aiLimit: '0 queries / day',
    features: [
      '1 GB storage quota',
      'Encrypted file vault',
      'Upload, download, and deletion',
      'Keyword search'
    ],
    badgeClass: 'badge-free',
    isComingSoon: false
  },
  privateVault: {
    id: 'private-vault',
    name: 'Premium',
    price: '₹100',
    period: '/ month',
    storage: '5 GB',
    aiLimit: '0 queries / day',
    features: [
      '5 GB storage quota',
      'Encrypted file vault',
      'Keyword search',
      'Resource-conscious concurrency management'
    ],
    badgeClass: 'badge-premium',
    isComingSoon: false
  },
  vaultAI: {
    id: 'vault-ai',
    name: 'AI Pro',
    price: '₹150',
    period: '/ month',
    storage: '5 GB',
    aiLimit: '100 local AI queries / day',
    features: [
      '5 GB storage quota',
      'Encrypted file vault',
      'Keyword and semantic search',
      'Local AI document Q&A',
      '100 local AI queries / day'
    ],
    badgeClass: 'badge-premium',
    isComingSoon: false
  },
  payg: {
    id: 'payg',
    name: 'Pay as you go',
    price: 'Pay as you go',
    period: '',
    storage: 'Unlimited',
    aiLimit: '100 local AI queries / day',
    features: [
      'Unlimited storage',
      'Encrypted file vault',
      'Keyword and semantic search',
      'Local AI document Q&A',
      'Existing resource-conscious concurrency limits'
    ],
    badgeClass: 'badge-coming-soon',
    isComingSoon: true
  }
};
