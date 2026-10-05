$users = @("0663835593SAMIR","0606060607","0606060606","0663835593","0699999999")
$headers = @{"X-Admin-Key"=""}
$uri = "https://backend-production-f0139.up.railway.app/api/admin/users"

foreach($u in $users) {
    $body = '{"phone":"' + $u + '","password":"changeme123","days":3650}'
    $r = Invoke-WebRequest -Uri $uri -Method POST -ContentType "application/json" -Headers $headers -Body $body -TimeoutSec 30 -ErrorAction Ignore
    Write-Host ("{0}: {1} {2}" -f $u, $r.StatusCode, $r.Content)
}