# -*- coding: utf-8 -*-
#
# Copyright © 2007  Red Hat, Inc. All rights reserved.
#
# This copyrighted material is made available to anyone wishing to use, modify,
# copy, or redistribute it subject to the terms and conditions of the GNU
# General Public License v.2.  This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY expressed or implied, including the
# implied warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.  You should have
# received a copy of the GNU General Public License along with this program;
# if not, write to the Free Software Foundation, Inc., 51 Franklin Street,
# Fifth Floor, Boston, MA 02110-1301, USA. Any Red Hat trademarks that are
# incorporated in the source code or documentation are not subject to the GNU
# General Public License and may only be used or replicated with the express
# permission of Red Hat, Inc.
#
# Red Hat Author(s): Luke Macken <lmacken@redhat.com>
#                    Toshio Kuratomi <tkuratom@redhat.com>
#

'''
fedora.client is used to interact with Fedora Services.
'''

import Cookie
import urllib
import urllib2
import logging
import cPickle as pickle
import re
import inspect
import simplejson
import os
import stat
from os import path
from urlparse import urljoin

import fedora.release

import gettext
translation = gettext.translation('python-fedora', '/usr/share/locale',
        fallback=True)
_ = translation.ugettext

log = logging.getLogger(__name__)

SESSION_FILE = path.join(path.expanduser('~'), '.fedora_session')

class FedoraServiceError(Exception):
    '''Base Exception for any problem talking with the Service.'''
    pass

class ServerError(FedoraServiceError):
    '''Unable to talk to the server properly.'''
    pass

class AuthError(FedoraServiceError):
    '''Error during authentication.  For instance, invalid password.'''
    pass

class AppError(FedoraServiceError):
    '''Error condition that the server is passing back to the client.'''
    pass

class BaseClient(object):
    '''
        A command-line client to interact with Fedora TurboGears Apps.
    '''
    def __init__(self, baseURL, username=None, password=None,
            useragent=None, debug=False):
        '''
        Arguments:
        :baseUrl: Base of every URL used to contact the server
        Keyword Arguments:
        :username: username for establishing authenticated connections
        :password: password to use with authenticated connections
        :useragent: useragent string to use.  If not given, default to
            "Fedora BaseClient/VERSION"
        :debug: If True, log debug information
        '''
        if baseURL[-1] != '/':
            baseURL = baseURL +'/'
        self.baseURL = baseURL
        self.username = username
        self.password = password
        self.useragent = useragent or 'Fedora BaseClient/%(version)s' % {
                'version': release.VERSION}
        self._sessionCookie = None

        # Setup our logger
        logHandler = logging.StreamHandler()
        if debug:
            log.setLevel(logging.DEBUG)
            logHandler.setLevel(logging.DEBUG)
        else:
            log.setLevel(logging.INFO)
            logHandler.setLevel(logging.INFO)
        format = logging.Formatter("%(message)s")
        logHandler.setFormatter(format)
        log.addHandler(logHandler)

        self._load_session()
        if username and password:
            self._authenticate(force=True)

    def _authenticate(self, force=False):
        '''
            Return an authenticated session cookie.
        '''
        if not force and self._sessionCookie:
            return self._sessionCookie
        if not self.username:
            raise AuthError, _('username must be set')
        if not self.password:
            raise AuthError, _('password must be set')

        req = urllib2.Request(urljoin(self.baseURL, 'login?tg_format=json'))
        req.add_header('User-agent', self.useragent)
        req.add_header('Accept', 'text/javascript')
        if self._sessionCookie:
            # If it exists, send the old sessionCookie so it is associated
            # with the request.
            req.add_header('Cookie', self._sessionCookie.output(attrs=[],
                header='').strip())
        req.add_data(urllib.urlencode({
                'user_name' : self.username,
                'password'  : self.password,
                'login'     : 'Login'
        }))

        try:
            loginPage = urllib2.urlopen(req)
        except urllib2.HTTPError, e:
            if e.msg == 'Forbidden':
                raise AuthError, _('Invalid username/password')
            else:
                raise

        loginData = simplejson.load(loginPage)

        if 'message' in loginData:
            raise AuthError, _('Unable to login to server: %(message)s') \
                    % loginData

        self._sessionCookie = Cookie.SimpleCookie()
        try:
            self._sessionCookie.load(loginPage.headers['set-cookie'])
        except KeyError:
            self._sessionCookie = None
            raise AuthError, _('Unable to login to the server.  Server did' \
                    ' not send back a cookie')
        self._save_session()

        return self._sessionCookie
    session = property(_authenticate)

    def _save_session(self):
        '''
            Store our pickled session cookie.
            
            This method loads our existing session file and modified our
            current user's cookie.  This allows us to retain cookies for
            multiple users.
        '''
        save = {}
        if path.isfile(SESSION_FILE):
            sessionFile = file(SESSION_FILE, 'r')
            # pylint: disable-msg=W0702
            try:
                save = pickle.load(sessionFile)
            except: # pylint: disable-msg=W0704
                # If there isn't a session file yet, there's no problem
                pass
            # pylint: enable-msg=W0702
            sessionFile.close()
        save[self.username] = self._sessionCookie
        try:
            sessionFile = file(SESSION_FILE, 'w')
            os.chmod(SESSION_FILE, stat.S_IRUSR | stat.S_IWUSR)
            pickle.dump(save, sessionFile)
            sessionFile.close()
        except Exception, e:
            # If we can't save the file, issue a warning but go on.  The
            # session just keeps you from having to type your password over
            # and over.
            log.warning(_('Unable to write to session file %(session)s:' \
                    ' %(error)s') % {'session': SESSION_FILE, 'error': str(e)})

    def _load_session(self):
        '''
            Load a stored session cookie.
        '''
        if path.isfile(SESSION_FILE):
            sessionFile = file(SESSION_FILE, 'r')
            try:
                savedSession = pickle.load(sessionFile)
                self._sessionCookie = savedSession[self.username]
                log.debug(_('Loaded session %(cookie)s') % \
                        {'cookie': self._sessionCookie})
            except EOFError:
                log.warning(_('Unable to load session from %(file)s') % \
                        {'file': SESSION_FILE})
            except KeyError:
                log.debug(_('Session is for a different user'))
            sessionFile.close()

    def logout(self):
        '''
            Logout from the server.
        '''
        try:
            self.send_request('logout', auth=True)
        except AuthError: # pylint: disable-msg=W0704
            # We don't need to fail for an auth error as we're getting rid of
            # our authentication tokens here.
            pass
      
    def send_request(self, method, auth=False, reqParams=None):
        '''Make an HTTP request to a server method.

        The given method is called with any parameters set in reqParams.  If
        auth is True, then the request is made with an authenticated session
        cookie.

        Arguments:
        :method: Method to call on the server.  It's a url fragment that comes
            after the baseURL set in __init__().
        :auth: If True perform auth to the server, else do not.
        :reqParams: Extra parameters to send to the server.
        '''
        method = method.lstrip('/')
        url = urljoin(self.baseURL, method + '?tg_format=json')

        response = None # the JSON that we get back from the server
        data = None     # decoded JSON via simplejson.load()

        log.debug(_('Creating request %(url)s') % {'url': url})
        req = urllib2.Request(url)
        req.add_header('User-agent', self.useragent)
        req.add_header('Accept', 'text/javascript')
        if reqParams:
            req.add_data(urllib.urlencode(reqParams))

        if auth:
            req.add_header('Cookie', self.session.output(attrs=[],
                header='').strip())
        elif self._sessionCookie:
            # If the cookie exists, send it so that visit tracking works.
            req.add_header('Cookie', self._sessionCookie.output(attrs=[],
                header='').strip())
        try:
            response = urllib2.urlopen(req)
        except urllib2.HTTPError, e:
            if e.msg == 'Forbidden':
                if (inspect.currentframe().f_back.f_code !=
                        inspect.currentframe().f_code):
                    self._authenticate(force=True)
                    return self.send_request(method, auth, reqParams)
                else:
                    # We actually shouldn't ever reach here.  Unless something
                    # goes drastically wrong _authenticate should raise an
                    # AuthError
                    log.error(e)
                    raise AuthError, _('Unable to log into server: %(error)s') \
                            % {'error': str(e)}
            else:
                raise

        # In case the server returned a new session cookie to us
        try:
            self._sessionCookie.load(response.headers['set-cookie'])
        except (KeyError, AttributeError): # pylint: disable-msg=W0704
            # It's okay if the server didn't send a new cookie
            pass

        jsonString = response.read()
        try:
            data = simplejson.loads(jsonString)
        except ValueError, e:
            # The response wasn't JSON data
            raise ServerError, str(e)

        if 'exc' in data:
            raise AppError(name = data['exc'], message = data['tg_flash'])

        if 'logging_in' in data:
            if (inspect.currentframe().f_back.f_code !=
                    inspect.currentframe().f_code):
                self._authenticate(force=True)
                data = self.send_request(method, auth, reqParams)
            else:
                # We actually shouldn't ever reach here.  Unless something goes
                # drastically wrong _authenticate should raise an AuthError
                raise AuthError, _('Unable to log into server: %(message)s') \
                        % data
        return data