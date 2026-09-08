import { defineConfig, devices } from '@playwright/test';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
const databasePath=join(tmpdir(),'pickmate-e2e.sqlite');
export default defineConfig({testDir:'./tests',timeout:30_000,fullyParallel:false,use:{baseURL:'http://127.0.0.1:5173',trace:'retain-on-failure'},webServer:[{command:'sh tests/start-api.sh',url:'http://127.0.0.1:8001/api/health',reuseExistingServer:false,env:{DATABASE_PATH:databasePath}},{command:'npm run dev -- --host 127.0.0.1 --port 5173',url:'http://127.0.0.1:5173',reuseExistingServer:false,env:{VITE_API_ROOT:'http://127.0.0.1:8001'}}],projects:[{name:'chromium',use:{...devices['Desktop Chrome']}},{name:'mobile',use:{...devices['Pixel 7']}}]});
