"""Existing domain/API tests run in explicitly opted-in offline local mode.

Production refuses this mode; TP-080A security tests switch to Supabase mode.
"""
import os

os.environ.setdefault("TASKPLANNER_ENV", "test")
os.environ.setdefault("TASKPLANNER_AUTH_MODE", "local")
