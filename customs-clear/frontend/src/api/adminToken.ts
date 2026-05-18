let adminToken = '';

export function getAdminToken(): string {
  return adminToken;
}

export function setAdminToken(value: string): void {
  adminToken = value.trim();
}

export function clearAdminToken(): void {
  adminToken = '';
}
