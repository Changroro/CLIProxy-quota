import assert from 'node:assert/strict';
import fs from 'node:fs';
import {messages} from '../cli_proxy_quota/web/i18n.js';
assert.deepEqual(Object.keys(messages.en).sort(),Object.keys(messages.ko).sort());
for (const value of Object.values(messages.en)) assert.ok(value);
for (const value of Object.values(messages.ko)) assert.ok(value);
const app=fs.readFileSync(new URL('../cli_proxy_quota/web/app.js',import.meta.url),'utf8');
for (const match of app.matchAll(/tr\(["']([^"']+)["']\)/g)) assert.ok(messages.en[match[1]],match[1]);
console.log('Web translation coverage passed');
