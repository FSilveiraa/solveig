#!/bin/bash


# Adds HISTTIMEFORMAT to ~/.bashrc if not already present

HIST_COMMENT_LINE='# Adds timestamps to your bash history (~/.bash_history)'
HIST_FORMAT_LINE='export HISTTIMEFORMAT="%F %T "'

if grep -q 'HISTTIMEFORMAT' ~/.bashrc; then
  echo "HISTTIMEFORMAT already set in ~/.bashrc"
else
  echo "$HIST_FORMAT_COMMENT" >> ~/.bashrc
  echo "$HIST_FORMAT_LINE" >> ~/.bashrc
  echo "Added HISTTIMEFORMAT to ~/.bashrc"
fi

echo "To apply changes, run: source ~/.bashrc"
