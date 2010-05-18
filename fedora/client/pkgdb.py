# -*- coding: utf-8 -*-
#
# Copyright (C) 2008-2010  Red Hat, Inc.
# This file is part of python-fedora
# 
# python-fedora is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
# 
# python-fedora is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public
# License along with python-fedora; if not, see <http://www.gnu.org/licenses/>
#
'''Module to provide a library interface to the package database.

.. moduleauthor:: Toshio Kuratomi <toshio@fedoraproject.org>
.. moduleauthor:: Mike Watters <valholla@fedoraproject.org>
.. moduleauthor:: Dmitry Kolesov <kolesovdv@fedoraproject.org>

.. versionadded:: 0.3.6
   Merge from CLI pkgdb-client

.. data:: COLLECTIONMAP

    Maps short names to Collections.  For instance, FC => Fedora
'''

import simplejson
import warnings

from fedora import __version__, _
from fedora.client import BaseClient, FedoraClientError, AppError

COLLECTIONMAP = {'F': 'Fedora',
    'FC': 'Fedora',
    'EL': 'Fedora EPEL',
    'EPEL': 'Fedora EPEL',
    'OLPC': 'Fedora OLPC',
    'RHL': 'Red Hat Linux'}

class PackageDBError(FedoraClientError):
    '''Errors generated by the PackageDB Client.'''
    pass

### FIXME: Port Exceptions on the server
# The PackageDB server returns errors errors as a dict with:
#   {'status': False, 'message': 'error message'}
# The new way of doing this is to set
#   {'exc': 'Exception name', tg_flash: 'error message'}
# So this needs to be ported on the server and we need to change error
# checking code to something like this:
# request = self.send_request([...])
# if 'exc' in request:
#   raise AppError(name=request['exc'], message=request['tg_flash'])
#
# Everywhere that currently sets AppError(name='PackageDBError',[...]) will
# need to be changed.

class PackageDB(BaseClient):

    def __init__(self, base_url='https://admin.fedoraproject.org/pkgdb/',
            *args, **kwargs):
        '''Create the PackageDB client.

        :kwarg base_url: Base of every URL used to contact the server.
            Defaults to the Fedora PackageDB instance.
        :kwarg useragent: useragent string to use.  If not given, default to
            "Fedora PackageDB Client/VERSION"
        :kwarg debug: If True, log debug information
        :type debug: bool
        :kwarg username: username for establishing authenticated connections
        :kwarg password: password to use with authenticated connections
        :kwarg session_id: user's session_id to connect to the server
        :type session_id: string
        :kwarg session_cookie: **Deprecated** use session_id instead.
            user's session_cookie to connect to the server
        :kwarg cache_session: if set to True, cache the user's session cookie
            on the filesystem between runs.
        :type kwarg: bool
        '''
        if 'useragent' not in kwargs:
            kwargs['useragent'] = 'Fedora PackageDB Client/%s' % __version__
        super(PackageDB, self).__init__(base_url, *args, **kwargs)
        self._branches = None

    def _get_branches(self, refresh=False):
        '''Return collection branch information from the packagedb.

        This method caches the branch information from the packagedb in
        self._branches.  It returns that information when called.

        :kwarg refresh: If refresh is set to True, contact the server even if
            the information was previously cached
        :returns: dictionary of branches keyed by their shortname
        '''
        if self._branches and not refresh:
            return self._branches
        data = self.send_request('/collections/')
        self._branches = dict((b[0]['branchname'], b[0])
                for b in data.collections)
        return self._branches
    branches = property(_get_branches)

    def get_package_info(self, pkg, branch=None):
        '''Get information about the package.

        :arg pkg: Name of the package
        :kwarg branch: If given, restrict information returned to this branch
            Allowed branches are listed in :data:`COLLECTIONMAP`
        :raises AppError: If the server returns an exceptiom
        :returns: Package ownership information
        :rtype: Bunch

        .. versionchanged:: 0.3.21
            Return Bunch instead of DictContainer
        '''
        data = None
        if branch:
            collection, ver = self.canonical_branch_name(branch)
            data = {'collectionName': collection, 'collectionVersion': ver}
        pkg_info = self.send_request('/acls/name/%s' % pkg,
                req_params=data)

        if 'status' in pkg_info and not pkg_info['status']:
            raise AppError(name='PackageDBError', message=pkg_info['message'])
        return pkg_info

    def clone_branch(self, pkg, branch, master, email_log=True):
        '''Set a branch's permissions from a pre-existing branch.

        :arg pkg: Name of the package to branch
        :arg branch: Branch to clone to.  Allowed branch names are listed in
            :data:`COLLECTIONMAP`
        :arg master: Short branch name to clone from.  Allowed branch names
            are listed in :data:`COLLECTIONMAP`
        :kwarg email_log: If False, do not email a copy of the log.
        :raises AppError: If the server returns an exceptiom

        '''
        params = {'email_log': email_log}
        return self.send_request('/acls/dispatcher/clone_branch/'
                '%s/%s/%s' % (pkg, branch, master), auth=True,
                req_params=params)

    def mass_branch(self, branch):
        '''Branch all unblocked packages for a new release.

        Mass branching always works against the devel branch.

        :arg branch: Branch name to create branches for.  Names are listed in
            :data:`COLLECTIONMAP`
        :raises AppError: If the server returns an exceptiom.  The 'extras'
            attribute will contain a list of unbranched packages if some of the
            packages were branched
        '''
        return self.send_request('/collections/mass_branch/%s' % branch,
                auth=True)

    def add_package(self, pkg, owner=None, description=None,
            branches=None, cc_list=None, comaintainers=None, groups=None):
        '''Add a package to the database.

        :arg pkg: Name of the package to edit
        :kwarg owner: If set, make this person the owner of both branches
        :kwarg description: If set, make this the description of both branches
        :kwarg branches: List of branches to operate on
        :kwarg cc_list: If set, list or tuple of usernames to watch the
            package.
        :kwarg comaintainers: If set, list or tuple of usernames to comaintain
            the package.
        :kwarg groups: If set, list or tuple of group names that can commit to
            the package.
        :raises AppError: If the server returns an error

        .. versionadded:: 0.3.13
        '''
        # See if we have the information to
        # create it
        if not owner:
            raise AppError(name='AppError', message=_('We do not have '
                    'enough information to create package %(pkg)s. '
                    'Need version owner.') % {'pkg': pkg})

        data = {'owner': owner, 'summary': description}
        # This call creates the package and an initial branch for
        # Fedora devel
        response = self.send_request('/acls/dispatcher/add_package/%s'
            % pkg, auth=True, req_params=data)
        if 'status' in response and not response['status']:
            raise AppError(name='PackageDBError', message=
                _('PackageDB returned an error creating %(pkg)s:'
                ' %(msg)s') % {'pkg': pkg, 'msg': response['message']})
            
        if cc_list:
            data['ccList'] = simplejson.dumps(cc_list)
        if comaintainers:
            data['comaintList'] = simplejson.dumps(comaintainers)

        # Parse the groups information
        if groups:
            data['groups'] = simplejson.dumps(groups)

        # Parse the Branch abbreviations into collections
        if branches:
            data['collections'] = []
            data['collections'] = branches
        del data['owner']

        if cc_list or comaintainers or groups or branches:
            response = self.send_request('/acls/dispatcher/'
                    'edit_package/%s' % pkg, auth=True, req_params=data)
            if 'status' in response and not response['status']:
                raise AppError(name='PackageDBError', 
                    message=_('Unable to save all information for'
                        ' %(pkg)s: %(msg)s') % {'pkg': pkg,
                        'msg': response['message']})

    def edit_package(self, pkg, owner=None, description=None,
            branches=None, cc_list=None, comaintainers=None, groups=None):
        '''Edit a package.

        :arg pkg: Name of the package to edit
        :kwarg owner: If set, make this person the owner of both branches
        :kwarg description: If set, make this the description of both branches
        :kwarg branches: List of branches to operate on
        :kwarg cc_list: If set, list or tuple of usernames to watch the
            package.
        :kwarg comaintainers: If set, list or tuple of usernames to comaintain
            the package.
        :kwarg groups: If set, list or tuple of group names that can commit to
            the package.
        :raises AppError: If the server returns an error

        This method takes information about a package and either edits the
        package to reflect the changes to information.

        Note: This method will be going away in favor of methods that do
        smaller chunks of work:

        1) A method to add a new branch
        2) A method to edit an existing package
        3) A method to edit an existing branch

        .. versionadded:: 0.3.13
        '''
        # Change the branches, owners, or anything else that needs changing
        data = {}
        if owner:
            data['owner'] = owner
        if description:
            data['summary'] = description
        if cc_list:
            data['ccList'] = simplejson.dumps(cc_list)
        if comaintainers:
            data['comaintList'] = simplejson.dumps(comaintainers)

        # Parse the groups information
        if groups:
            data['groups'] = simplejson.dumps(groups)

        # Parse the Branch abbreviations into collections
        if branches:
            data['collections'] = []
            data['collections'] = branches

        # Request the changes
        response = self.send_request('/acls/dispatcher/edit_package/%s'
                % pkg, auth=True, req_params=data)
        if 'status' in response and not response['status']:
            raise AppError(name='PackageDBError', message=_('Unable to save'
                ' all information for %(pkg)s: %(msg)s') % {'pkg': pkg,
                    'msg': response['message']})

    def canonical_branch_name(self, branch):
        '''Change a branch abbreviation into a name and version.

        :arg branch: branch abbreviation
        :rtype: tuple
        :returns: tuple of branch name and branch version.

        Example:
        >>> name, version = canonical_branch_name('FC-6')
        >>> name
        Fedora
        >>> version
        6
        '''
        # This is a small change in behaviour.  Might as well wait for the 
        # pkgdb update.
        #try:
        #    collection = self.branches[branch]
        #except KeyError:
        #    raise PackageDBError(_('Collection %(branch)s does not exist in'
        #        ' the packagedb') % {'branch': branch})
        #return collection['name'], collection['version']

        if branch == 'devel':
            collection = 'Fedora'
            version = 'devel'
        else:
            collection, version = branch.split('-')
            try:
                collection = COLLECTIONMAP[collection]
            except KeyError:
                raise PackageDBError(_('Collection abbreviation'
                        ' %(collection)s is unknown.  Use F, FC, EL, or OLPC')
                        % {'collection': collection})

        return collection, version

    def get_owners(self, package, collctn_name=None, collctn_ver=None,
                                  collection=None, collection_ver=None):
        '''Retrieve the ownership information for a package.

        :arg package: Name of the package to retrieve package information about.
        :kwarg collctn_name: Limit the returned information to this collection
            ('Fedora', 'Fedora EPEL', Fedora OLPC', etc)
        :kwarg collctn_ver: If collection is specified, further limit to this
            version of the collection.
        :kwarg collection: old/deprecated argument; use collctn_name
        :kward collection_ver: old/deprecated argument; use collctn_ver
        :raises AppError: If the server returns an error
        :rtype: Bunch
        :return: dict of ownership information for the package

        .. versionchanged:: 0.3.17
            Rename collection and collection_ver to collctn_name and collctn_ver
        .. versionchanged:: 0.3.21
            Return Bunch instead of DictContainer
        '''
        if (collctn_name and collection) or (collctn_ver and collection_ver):
            warnings.warn(_('collection and collection_ver are deprecated'
                ' names for collctn_name and collctn_ver respectively.'
                '  Ignoring the values given in them.'), DeprecationWarning,
                stacklevel=2)

        if collection and not collctn_name:
            warnings.warn(_('collection has been renamed to collctn_name.\n'
                'Please start using the new name.  collection will go '
                'away in 0.4.x.'), DeprecationWarning, stacklevel=2)
            collctn_name = collection

        if collection_ver and not collctn_ver:
            warnings.warn(_('collection_ver has been renamed to collctn_ver.\n'
                'Please start using the new name.  collection_ver will go '
                'away in 0.4.x.'), DeprecationWarning, stacklevel=2)
            collctn_ver = collection_ver

        method = '/acls/name/%s' % package
        if collctn_name:
            method = method + '/' + collctn_name
            if collctn_ver:
                method = method + '/' + collctn_ver

        response = self.send_request(method)
        if 'status' in response and not response['status']:
            raise AppError(name='PackageDBError', message=response['message'])
        ###FIXME: Really should reformat the data so we show either a
        # dict keyed by collection + version or
        # list of collection, version, owner
        return response

    def remove_user(self, username, pkg_name, collctn_list=None,
            collectn_list=None):
        '''Remove user from a package

        :arg username: Name of user to remove from the package
        :arg pkg_name: Name of the package
        :kwarg collctn_list: list of collection simple names like
            'F-10','devel'.  Default: None which means user removed from all
            collections associated with the package.
        :kwarg collectn_list: *Deprecated* Use collctn_list instead.
        :returns: status code from the request

        .. versionadded:: 0.3.12

        .. versionchanged:: 0.3.17
            Rename collectn_list to collctn_list
        '''
        if (collctn_list and collectn_list):
            warnings.warn(_('collectn_list is a deprecated name for'
                    ' collctn_list.\nIgnoring the value of collectn_list.'),
                    DeprecationWarning, stacklevel=2)

        if collectn_list and not collctn_list:
            warnings.warn(_('collectn_list has been renamed to collctn_list.\n'
                    'Please start using the new name.  collectn_list will go'
                    ' away in 0.4.x.'), DeprecationWarning, stacklevel=2)
            collctn_list = collectn_list

        if collctn_list:
            params = {'username': username, 'pkg_name': pkg_name, 
                'collectn_list': collctn_list}
        else:
            params = {'username': username, 'pkg_name': pkg_name}
        return self.send_request('/acls/dispatcher/remove_user', auth=True,
                   req_params=params)

    def user_packages(self, username, acls=None, eol=False):
        '''Retrieve information about the packages a user owns

        :arg username: user whose packages we want
        :kwarg acls: list of acls that the user must have on the package.
            The list can include 'owner', 'approveacls', 'commit',
            'watchbugzilla', 'watchcommits'.  Default is to select for all
            acls.
        :kwarg eol: If True, then include ownership of packages in End of Life
            distributions.  If False, only include ownership of packages in
            active releases.
        :returns: packages that the user has acls on

        .. versionadded:: 0.3.14
        '''
        params = {'eol': eol, 'tg_paginate_limit': 0}
        if acls:
            params['acls'] = acls
        return self.send_request('/users/packages/%s' % username,
                req_params=params)

    def orphan_packages(self):
        '''List the packages which are orphaned

        :returns: List of pkgs which are orphaned in any non-EOL release.
        '''
        params = {'tg_paginate_limit': 0}
        data = self.send_request('/acls/orphans', req_params=params)
        return data.pkgs

    def get_collection_list(self, eol=True):
        '''Retrieve a list of all collections.

        :kwarg eol: Default True.  If set to False, do not return collections
            marked eol.
        :returns: list of collections
        '''
        ### TODO: Once the server is updated to 0.5.x, we can update this to use
        # req_params={'eol': eol} instead of postprocessing it.
        data = self.send_request('/collections/')
        if not eol:
            collections = [c for c in data.collections if
                    c[0]['statuscode'] != 9]
            data.collections = collections
        return data.collections

    def get_package_list(self, collctn=None, collectn=None):
        '''Retrieve a list of all package names in a collection.

        :kwarg collctn: Collection to look for packages in.  This is a collctn
            shortname like 'devel' or 'F-13'.  If unset, return packages in
            all collections
        :kwarg collectn: *Deprecated*.  Please use collctn instead
        :returns: list of package names present in the collection.

        .. versionadded:: 0.3.15

        .. versionchanged:: 0.3.17
            Rename collectn to collctn
        '''
        if (collctn and collectn):
            warnings.warn(_('collectn is a deprecated name for'
                    ' collctn.\nIgnoring the value of collectn.'),
                    DeprecationWarning, stacklevel=2)

        if collectn and not collctn:
            warnings.warn(_('collectn has been renamed to collctn.\n'
                    'Please start using the new name.  collectn will go'
                    ' away in 0.4.x.'), DeprecationWarning, stacklevel=2)
            collctn = collectn

        params = {'tg_paginate_limit': '0'}
        if collctn:
            try:
                collctn_id = self.branches[collctn]['id']
            except KeyError:
                raise PackageDBError(_('Collection shortname %(collctn)s'
                    ' is unknown.') % {'collctn': collctn})
            data = self.send_request('/collections/name/%s/' % collctn, params)
        else:
            data = self.send_request('/acls/list/*', params)
        names = [p['name'] for p in data.packages]
        return names

    def get_vcs_acls(self):
        '''Return the acls for the version control system.

        Note: the return values from this function will be changing when the
        PackageDB updates to 0.5.x.  The return data will look like this::

            data[pkg][branch].people
            data[pkg][branch].groups

        :rtype: Bunch
        :returns: `Bunch` representing the vcs acls for every person.
            It looks like this: data[pkg][branch]['commit'].people list of
            users who can commit to the package.  Example::

                >>> print data['bzr']['devel']['commit'].people
                ['toshio', 'hno', 'shahms', 'toshio']
                >>> print data['bzr']['devel']['commit'].groups
                ['provenpackager']

        .. versionadded:: 0.3.15
        .. versionchanged:: 0.3.21
            Return Bunch instead of DictContainer
        '''
        data = self.send_request('/lists/vcs')
        if 'exc' in data:
            raise AppError(data['exc'], data['tg_flash'])

        return data.packageAcls

    def get_bugzilla_acls(self):
        '''Return the package attributes used by bugzilla.

        :rtype: Bunch
        :returns: `Bunch` contains information needed to setup bugzilla
            for every collection.  It looks like this:
            data[collctn][pkg][attribute] where attribute is one of:
            :owner: FAS username for the owner
            :qacontact: if the package hasa special qacontact, their userid is listed here
            :summary: Short description of the package
            :cclist: list of FAS userids that are watching the package

            Example::
                >>> print data['Fedora']['bzr']['owner']
                'toshio'
                >>> print data['Fedora']['bzr']['qacontact']
                None
                >>> print data['Fedora']['bzr']['summary']
                'Friendly distributed version control system'
                >>> print data['Fedora']['bzr']['cclist']
                {'groups': [], 'people': ['hno', 'shahms', 'toshio']}
                >>> data.keys()
                ['Fedora OLPC', 'Fedora', 'Fedora EPEL']

        .. versionadded:: 0.3.15
        .. versionchanged:: 0.3.21
            Return Bunch instead of DictContainer
        '''
        data = self.send_request('/lists/bugzilla')
        if 'exc' in data:
            raise AppError(data['exc'], data['tg_flash'])

        return data.bugzillaAcls

    def get_notify_acls(self, collctn_name=None, collctn_ver=None, eol=False):
        '''Return the package attibutes used by notify

        :kwarg collctn_name: Limit the packages to those in collection with
            this name.  for instance, 'Fedora', 'Fedora EPEL', 'Fedora OLPC'.
        :kwarg collctn_ver: If collctn_name is specified, this allows you to
            also limit to a specific version of a collection.  If collctn_name
            isn't specified, this option does nothing.
        :kwarg eol: If eol is set to True, include eol distributions in the
            notify list.  Default: False
        :kwarg role_list: Note, this will not do anything until pkgdb-0.5.
            List of roles that the user must have the acls for in order to be
            included.  Valid roles are: owner, comaintainer, committer,
            bzwatcher, and vcswatcher
        :rtype: Bunch
        :returns: `Bunch` keyed on package name.  Each entry has a list
            of people to be notified for this package.

        .. versionadded:: 0.3.15
        .. versionchanged:: 0.3.21
            Return Bunch instead of DictContainer
        '''
        method = '/lists/notify' 
        if collctn_name:
            method = method + '/' + collctn_name
            if collctn_ver:
                method = method + '/' + collctn_ver

#        params = {'eol': eol, 'tg_paginate_limit': 0}
        params = {'eol': eol}
        data = self.send_request(method, req_params=params)
        if 'exc' in data:
            raise AppError(data['exc'], data['tg_flash'])
        return data.packages

    def get_critpath_pkgs(self, collctn_list=None):
        '''Return names of packages marked critical path.

        :kwarg collctn_list: When set to a list of Collection names, only
            retrieve packages which are marked critpath in any of the
            collections.  Defaults to retrieving critpath packages in all
            non-EOL releases
        :rtype: Bunch
        :returns: Keys of the returned dict are collection simple names.  The
            values are lists of package names that are marked critpath

        .. versionadded:: 0.3.17
        .. versionchanged:: 0.3.21
            Return Bunch instead of DictContainer
        '''
        if collctn_list:
            params = {'collctn_list': collctn_list}
        else:
            params = {}

        data = self.send_request('/lists/critpath', req_params=params)

        return data['pkgs']

    def set_critpath(self, pkg_list=None, critpath=True, collctn_list=None,
            reset=False):
        '''Mark packages as being in the critical path.

        Critical path packages are subject to more testing or stringency of
        criteria for updating when a release occurs.

        :kwarg pkg_list: List of package names to set as critical path.
            Default: all packages within `collectn_list`
        :kwarg critpath: Boolean.  True (default) means this package is in the
            critical path.  False means that it should be taken out
        :kwarg collctn_list: List of collection shortnames that this change
            will be applied on.  The default is all non-EOL collections.
        :kwarg reset: If True, clear the critpath flag from all packages in
            collectn_list before setting critpath on the packages in pkg_list.
            Default is False

        .. versionadded:: 0.3.17
        '''
        params = {'critpath': critpath, 'reset': reset}
        if pkg_list:
            params['pkg_list'] = pkg_list
        if collctn_list:
            params['collctn_list'] = collctn_list

        self.send_request('/acls/dispatcher/set_critpath', req_params=params,
                auth=True)
