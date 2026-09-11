# Cloudflare Pages Deployment Script for AutoTrace Web
param (
    [string]$ProjectName = "autotrace-web"
)

$ErrorActionPreference = "Stop"

Write-Host "Building Next.js app with @cloudflare/next-on-pages..." -ForegroundColor Yellow
Set-Location "$PSScriptRoot/../node_modules/apps/web"

npx @cloudflare/next-on-pages

Write-Host "Deploying to Cloudflare Pages..." -ForegroundColor Yellow
npx wrangler pages deploy .vercel/output/static --project-name $ProjectName

Write-Host "Cloudflare Pages deployment finished!" -ForegroundColor Green
