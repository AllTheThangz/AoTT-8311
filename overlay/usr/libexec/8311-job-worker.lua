#!/usr/bin/lua
local jobs = require "8311.jobs"
os.exit(jobs.worker(arg[1]))
