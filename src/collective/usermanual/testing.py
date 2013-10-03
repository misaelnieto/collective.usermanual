# -*- coding: utf-8 -*-
import os
import sys

from Acquisition import aq_base

from zope.component.hooks import (
    getSiteManager
)

from plone.app.robotframework import (
    AutoLogin,
    RemoteLibraryLayer
)

from plone import api
from plone.uuid.interfaces import IUUID
from zope.configuration import xmlconfig
from plone.app.robotframework.remote import RemoteLibrary
from plone.app.testing import (
    PLONE_FIXTURE,
    ploneSite,
    PloneSandboxLayer
)
from plone.app.testing.layers import FunctionalTesting
from Products.MailHost.interfaces import IMailHost

from plone.testing import (
    Layer,
    z2
)

from robot.libraries.BuiltIn import BuiltIn

class MockMailHostLayer(Layer):
    """Layer for setting up a MockMailHost to store all sent messages as
    strings into a list at portal.MailHost.messages

    """
    defaultBases = (PLONE_FIXTURE,)

    def setUp(self):
        # Note: CMFPlone can be imported safely only when a certain
        # zope.testing-set environment variable is in place.
        from Products.CMFPlone.tests.utils import MockMailHost
        with ploneSite() as portal:
            portal.email_from_address = 'noreply@example.com'
            portal.email_from_name = 'Plone Site'
            portal._original_MailHost = portal.MailHost
            portal.MailHost = mailhost = MockMailHost('MailHost')
            portal.MailHost.smtp_host = 'localhost'
            sm = getSiteManager(context=portal)
            sm.unregisterUtility(provided=IMailHost)
            sm.registerUtility(mailhost, provided=IMailHost)

    def tearDown(self):
        with ploneSite() as portal:
            portal.MailHost = portal._original_MailHost
            sm = getSiteManager(context=portal)
            sm.unregisterUtility(provided=IMailHost)
            sm.registerUtility(aq_base(portal._original_MailHost),
                               provided=IMailHost)

MOCK_MAILHOST_FIXTURE = MockMailHostLayer()


class CustomRemoteKeywords(RemoteLibrary):
    """Useful remote keywords, which are run inside a normal ZPublisher-request
    environment with all the related Plone-magic in place

    """

    def create_user(self, username, *args, **kwargs):
        """Create user with given details and return its id
        """
        # XXX: It seems that **kwargs does not yet work with Robot Framework
        # remote library interface and that's why we need to unpack the
        # keyword arguments from positional args list.
        roles = []
        properties = {}
        for arg in args:
            if not '=' in arg:
                roles.append(arg)
            else:
                name, value = arg.split('=', 1)
                if name in ('email', 'password'):
                    kwargs[name] = value
                else:
                    properties[name] = value
        if not 'email' in kwargs:
            kwargs['email'] = '%s@example.com' % username
        return api.user.create(
            username=username, roles=roles, properties=properties, **kwargs)

    def create_content(self, *args, **kwargs):
        """Create content and return its UID
        """
        # XXX: It seems that **kwargs does not yet work with Robot Framework
        # remote library interface and that's why we need to unpack the
        # keyword arguments from positional args list.
        for arg in args:
            name, value = arg.split('=', 1)
            kwargs[name] = value
        assert 'id' in kwargs, u"Keyword arguments must include 'id'."
        assert 'type' in kwargs, u"Keyword arguments must include 'type'."
        if 'container' in kwargs:
            kwargs['container'] = api.content.get(UID=kwargs['container'])
        else:
            kwargs['container'] = api.portal.get()

        # Pre-fill Image-types with random content
        if kwargs.get('type') == 'Image' and not 'image' in kwargs:
            import random
            import StringIO
            from PIL import (
                Image,
                ImageDraw
            )
            img = Image.new('RGB', (random.randint(320, 640),
                                    random.randint(320, 640)))
            draw = ImageDraw.Draw(img)
            draw.rectangle(((0, 0), img.size), fill=(random.randint(0, 255),
                                                     random.randint(0, 255),
                                                     random.randint(0, 255)))
            del draw

            kwargs['image'] = StringIO.StringIO()
            img.save(kwargs['image'], 'PNG')
            kwargs['image'].seek(0)

        return IUUID(api.content.create(**kwargs))

    def apply_profile(self, name):
        """Apply named profile
        """
        self.portal_setup.runAllImportStepsFromProfile('profile-%s' % name)

    def do_workflow_action_for(self, content, action):
        """Do worklflow action for content
        """
        obj = self.portal_catalog.unrestrictedSearchResults(
            UID=content)[0]._unrestrictedGetObject()
        self.portal_workflow.doActionFor(obj, action)

    def set_default_language(self, language):
        """Change portal default language
        """
        setattr(self.portal_url.getPortalObject(), 'language', language)
        self.portal_languages.setDefaultLanguage(language)

    def get_the_last_sent_email(self):
        """Return the last sent email from MockMailHost sent messages storage
        """
        return self.MailHost.messages[-1] if self.MailHost.messages else u""

USERMANUAL_REMOTE_LIBRARY_FIXTURE = RemoteLibraryLayer(
    bases=(PLONE_FIXTURE,),
    libraries=(AutoLogin, CustomRemoteKeywords),
    name="UserManual:RobotRemote"
)


class UserManualLayer(PloneSandboxLayer):
    defaultBases = (MOCK_MAILHOST_FIXTURE,
                    USERMANUAL_REMOTE_LIBRARY_FIXTURE)

    def _get_robot_variable(self, name):
        """Return robot list variable either from robot instance or
        from ROBOT_-prefixed environment variable
        """
        if getattr(BuiltIn(), '_context', None) is not None:
            return BuiltIn().get_variable_value('${%s}' % name, [])
        else:
            candidates = os.environ.get(name, '').split(',')
            return filter(bool, [s.strip() for s in candidates])

    def setUpZope(self, app, configurationContext):

        for name in self._get_robot_variable('META_PACKAGES'):
            if not name in sys.modules:
                __import__(name)
            package = sys.modules[name]
            xmlconfig.file('meta.zcml', package,
                           context=configurationContext)

        for name in self._get_robot_variable('CONFIGURE_PACKAGES'):
            if not name in sys.modules:
                __import__(name)
            package = sys.modules[name]
            xmlconfig.file('configure.zcml', package,
                           context=configurationContext)

        for name in self._get_robot_variable('OVERRIDE_PACKAGES'):
            if not name in sys.modules:
                __import__(name)
            package = sys.modules[name]
            xmlconfig.includeOverrides(
                configurationContext, 'overrides.zcml', package=package)

        for name in self._get_robot_variable('INSTALL_PACKAGES'):
            if not name in sys.modules:
                __import__(name)
            package = sys.modules[name]
            z2.installProduct(app, package)

    def setUpPloneSite(self, portal):

        for name in self._get_robot_variable('APPLY_PROFILES'):
            self.applyProfile(portal, name)

        portal.portal_workflow.setDefaultChain("simple_publication_workflow")


USERMANUAL_FIXTURE = UserManualLayer()


USERMANUAL_ROBOT_TESTING = FunctionalTesting(
    bases=(USERMANUAL_FIXTURE, z2.ZSERVER_FIXTURE),
    name="UserManual:Robot"
)
