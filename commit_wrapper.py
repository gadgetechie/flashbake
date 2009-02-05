#!/usr/bin/env python
#
#  commit-wrapper.py
#  Parses a project's control file and wraps git operations, calling the context
#  script to build automatic commit messages as needed.
#
#  version 0.6 - improved logging, more quoting of arguments to shell
#
#  history:
#  version 0.5 - consolidate commits
#  version 0.4 - Added quotes to git call for filenames with spaces
#  version 0.3 - SMTP port, she-bang
#  version 0.2 - email notification
#  version 0.1 - git functionality complete
#
#  Created by Thomas Gideon (cmdln@thecommandline.net) on 1/25/2009
#  Provided as-is, with no warranties
#  License: http://creativecommons.org/licenses/by-nc-sa/3.0/us/ 

import os
import sys
import re
import datetime
import time
import commit_context
# this import is only valid for Linux
import commands
# Import smtplib for the actual sending function
import smtplib
# Import the email modules we'll need
from email.mime.text import MIMEText


def go(project_dir, quiet_mins):
    print 'Checking %s' % project_dir
    # change to the project directory, necessary to find the .control file and
    # to correctly refer to the project files by relative paths
    os.chdir(project_dir)
    # read the control file into a hashable set to compare git status entries
    # more easily against the possible subset that should be controlled by the
    # script
    control_file = open('.control', 'r')
    control_files = set()
    # TODO replace these with a config object
    feed = None
    limit = None
    author = None
    email = None
    notice_to = None
    notice_from = None
    smtp_port = None
    try:
        for line in control_file:
            if line.startswith('#'):
                continue
            elif line.startswith('feed:'):
                feed = line.split(':', 1)[1].strip()
            elif line.startswith('limit:'):
                limit = int(line.split(':')[1].strip())
            elif line.startswith('author:'):
                author = line.split(':')[1].strip()
            elif line.startswith('notice_from:'):
                notice_from = line.split(':')[1].strip()
            elif line.startswith('notice_to:'):
                notice_to = line.split(':')[1].strip()
            elif line.startswith('smtp_port:'):
                smtp_port = int(line.split(':')[1].strip())
            elif len(line.strip()) == 0:
                continue
            else:
                control_files.add(line.strip())
    finally:
        control_file.close()

    if notice_from == None and notice_to != None:
        notice_from = notice_to

    if feed == None or limit == None or author == None or notice_to == None:
        print 'Make sure that feed:, limit:, author:, and notice_to: are in the .control file'
        sys.exit(1)

    message_file = commit_context.build_message_file(feed, limit, author)
    # get the git status for the project
    git_status = commands.getoutput('git status')

    # in particular find the existing entries that need a commit
    pending_re = re.compile('#\s*(renamed|copied|modified|new file):.*')

    now = datetime.datetime.today()
    quiet_period = datetime.timedelta(minutes=quiet_mins)

    git_commit = 'git commit -F %(msg_filename)s %(filenames)s'
    file_template = ' "%s"'
    to_commit = ''
    # first look in the files git already knows about
    for line in git_status.splitlines():
        if pending_re.match(line):
            pending_file = trim_git(line)
            if not (pending_file in control_files):
                continue
            print 'Parsing status line %s to determine commit action' % line
            # remove files that will be considered for commit
            control_files.remove(pending_file)
            last_mod = os.path.getmtime(pending_file)
            pending_mod = datetime.datetime.fromtimestamp(last_mod)
            pending_mod += quiet_period
            # add the file to the list to include in the commit
            if pending_mod < now:
                to_commit += file_template % pending_file
                print 'Flagging file, %s, for commit.' % pending_file
            else:
                print 'Change for file, %s, is too recent.' % pending_file
    # consolidate the commit to be friendly to how git normally works
    git_commit = git_commit % {'msg_filename' : message_file, 'filenames' : to_commit}
    print git_commit
    commit_output = commands.getoutput(git_commit)
    #print commit_output
    print 'Commit complete.'

    # find the control files that aren't in the project directory to notify that
    # they need to be added
    print '\nExamining files that were not committed.'
    git_status = 'git status "%s"'
    not_exists = set()
    to_add = set()
    for control_file in control_files:
        if not os.path.exists(control_file):
            print '%s does not exist yet.' % control_file
            not_exists.add(control_file)
            continue;

        status_output = commands.getoutput(git_status % control_file)

        if status_output.startswith('error'):
            if status_output.find('did not match') > 0:
                to_add.add(control_file)
                print '%s exists but is unknown by git.' % control_file
            else:
                print 'Unknown error occurred!'
                print status_output
            continue
        if status_output.find(control_file) < 0:
            print '%s has no uncommitted changes.' % control_file
        else:
            print status_output
    if len(to_add) > 0 or len(not_exists) > 0:
        send_orphans(notice_to, notice_from, smtp_port, project_dir, to_add, not_exists)

def trim_git(status_line):
    if status_line.find('->') >= 0:
        tokens = status_line.split('->')
        return tokens[1].strip()

    tokens = status_line.split(':')
    return tokens[1].strip()

def send_orphans(notice_to, notice_from, smtp_port, project_dir, orphans, not_exists):
    body = 'Use "git status" to check whether git knows about these files.\n'
    
    if len(not_exists) > 0:
        body += '\nThe following files do not exist:\n\n'

        for file in not_exists:
           body += '\t' + file + '\n'

        body += '\nMake sure there is not a typo in .control and that you created/saved the file.\n'
    
    if len(orphans) > 0:
        body += '\nThe following files exist but must be added:\n\n'

        for file in orphans:
           body += '\t' + file + '\n'

        body += '\nUse "git add <file>" to add a file that does exist but is unknown to git.\n'

    # Create a text/plain message
    msg = MIMEText(body, 'plain')

    msg['Subject'] = 'Some files in %s do not exist' % project_dir
    msg['From'] = notice_from
    msg['To'] = notice_to

    # Send the message via our own SMTP server, but don't include the
    # envelope header.
    print '\nConnecting to SMTP port %d' % smtp_port
    s = smtplib.SMTP()
    s.connect(port=smtp_port)
    print 'Sending notice to %s.' % notice_to
    s.sendmail(notice_from, [notice_to], msg.as_string())
    s.close()

# call go() when this module is executed as the main script
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print "%s <project directory> <quiet period>" % sys.argv[0]
        sys.exit(1)

    project_dir = sys.argv[1]
    quiet_period = int(sys.argv[2])
    go(project_dir, quiet_period)