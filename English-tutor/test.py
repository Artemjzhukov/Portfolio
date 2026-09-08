$apiKey = "bd81fa8ed3f14db590bef62d8c3276fe.uMuMuaVh22eRXZir"
$headers = @{
    "Authorization" = "Bearer $apiKey"
    "Content-Type"  = "application/json"
}
$body = @{
    model = "glm-4.5"
    messages = @(@{role="user"; content="Hello, respond with ONE word 'Ready'"})
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod -Uri "https://open.bigmodel.cn/api/paas/v4/chat/completions" -Method Post -Headers $headers -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
$response.choices[0].message.content