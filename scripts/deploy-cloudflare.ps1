# Cloudflare Pages Deployment Script for PingWatch Web
param (
    [string]$ProjectName = "pingwatch-web"
)

$ErrorActionPreference = "Stop"

Write-Host "Building Next.js app with @cloudflare/next-on-pages..." -ForegroundColor Yellow
Set-Location "$PSScriptRoot/../apps/web"

npx @cloudflare/next-on-pages

Write-Host "Deploying to Cloudflare Pages..." -ForegroundColor Yellow
npx wrangler pages deploy .vercel/output/static --project-name $ProjectName

Write-Host "Cloudflare Pages deployment finished!" -ForegroundColor Green
