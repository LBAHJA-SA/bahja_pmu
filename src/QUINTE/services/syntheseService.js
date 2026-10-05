export async function fetchSyntheseFingerprint(participants, hippodrome, distance, runners) {
  const res = await fetch('/api/synthese/fingerprint', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ participants, hippodrome, distance, runners })
  })
  if (!res.ok) throw new Error('Synthèse fingerprint failed')
  return res.json()
}

export async function fetchSyntheseMatch(participants, hippodrome, distance, runners, presse, disc) {
  const res = await fetch('/api/synthese/match', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ participants, hippodrome, distance, runners, presse, disc })
  })
  if (!res.ok) throw new Error('Synthèse match failed')
  return res.json()
}
