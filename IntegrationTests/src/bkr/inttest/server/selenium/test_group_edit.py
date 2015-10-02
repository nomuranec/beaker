
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import crypt
import requests
from turbogears.database import session
from bkr.server.model import Group, User, Activity, UserGroup
from bkr.inttest.server.selenium import WebDriverTestCase
from bkr.inttest import data_setup, get_server_base, with_transaction, \
    mail_capture, DatabaseTestCase
from bkr.inttest.server.webdriver_utils import login, logout, \
        wait_for_animation, check_group_search_results
from bkr.inttest.assertions import wait_for_condition
from bkr.inttest.server.requests_utils import put_json, post_json, patch_json
import email

class TestGroupsWD(WebDriverTestCase):

    def setUp(self):
        with session.begin():
            self.user = data_setup.create_user(password='password')
            self.group = data_setup.create_group()
            self.perm1 = data_setup.create_permission()
            self.group.add_member(self.user, is_owner=True)
        self.browser = self.get_browser()
        self.clear_password = 'gyfrinachol'
        self.hashed_password = '$1$NaCl$O34mAzBXtER6obhoIodu8.'
        self.simple_password = 's3cr3t'

        self.mail_capture = mail_capture.MailCaptureThread()
        self.mail_capture.start()
        self.addCleanup(self.mail_capture.stop)

    def go_to_group_page(self, group=None, tab=None):
        if group is None:
            group = self.group
        b = self.browser
        b.get(get_server_base() + group.href)
        b.find_element_by_xpath('//title[normalize-space(text())="%s"]' % \
            group.group_name)
        if tab:
            b.find_element_by_xpath('//ul[contains(@class, "group-nav")]'
                    '//a[text()="%s"]' % tab).click()

    def test_edit_button_is_absent_when_not_logged_in(self):
        b = self.browser
        self.go_to_group_page()
        b.find_element_by_xpath('//div[@id="group-details" and '
                'not(.//button[normalize-space(string(.))="Edit"])]')

    def test_add_bad_permission(self):
        b = self.browser
        login(b)
        self.go_to_group_page(tab=u'Permissions')
        b.find_element_by_name('group_permission').send_keys('dummy_perm')
        b.find_element_by_class_name('add-permission').submit()
        #Test that it has not been dynamically added
        b.find_element_by_xpath('//div[contains(@class, "alert-error") and '
            'contains(string(.), "%s")]' % "Permission 'dummy_perm' does not exist")

        #Double check that it wasn't added to the permissions
        b.find_element_by_xpath('//div/ul[@class="list-group group-permissions-list" and '
                'not(.//li[contains(text(), "dummy_perm")])]')

        #Triple check it was not persisted to the DB
        self.go_to_group_page(tab=u'Permissions')
        b.find_element_by_xpath('//div/ul[@class="list-group group-permissions-list" and '
                'not(.//li[contains(text(), "dummy_perm")])]')

    def test_add_and_remove_permission(self):
        b = self.browser
        login(b)

        self.go_to_group_page(tab=u'Permissions')
        b.find_element_by_name('group_permission').send_keys(self.perm1.permission_name)
        b.find_element_by_class_name('add-permission').submit()
        #Test that permission dynamically updated
        b.find_element_by_xpath('//div/ul[@class="list-group group-permissions-list" and '
            '//li[contains(text(), "%s")]]' % self.perm1.permission_name)
        #Test that the permission was persisted by reopening the current page
        self.go_to_group_page(tab=u'Permissions')
        b.find_element_by_xpath('//div/ul[@class="list-group group-permissions-list" and '
            '//li[contains(text(), "%s")]]'  % self.perm1.permission_name)
        #Let's try and remove it
        b.find_element_by_xpath('//div/ul[@class="list-group group-permissions-list"]'
           '/li[contains(text(), "%s")]/button' % self.perm1.permission_name).click()
        #Check it has been removed from the list
        b.find_element_by_xpath('//div/ul[@class="list-group group-permissions-list" and '
            'not(.//li[contains(text(), "%s")])]' % self.perm1.permission_name)

        #Reload to make sure it has been removed from the DB
        self.go_to_group_page(tab=u'Permissions')
        b.find_element_by_xpath('//div/ul[@class="list-group group-permissions-list" and '
            'not(.//li[contains(text(), "%s")])]' % self.perm1.permission_name)

    # https://bugzilla.redhat.com/show_bug.cgi?id=1012373
    def test_add_then_immediately_remove_permission(self):
        b = self.browser
        login(b)
        self.go_to_group_page(tab=u'Permissions')
        b.find_element_by_name('group_permission').send_keys(self.perm1.permission_name)
        b.find_element_by_class_name('add-permission').submit()
        b.find_element_by_xpath('//div/ul[@class="list-group group-permissions-list"]'
           '/li[contains(text(), "%s")]/button' % self.perm1.permission_name).click()
        b.find_element_by_xpath('//div/ul[@class="list-group group-permissions-list" and '
            'not(.//li[contains(text(), "%s")])]' % self.perm1.permission_name)

    def check_notification(self, user, group, action):
        self.assertEqual(len(self.mail_capture.captured_mails), 1)
        sender, rcpts, raw_msg = self.mail_capture.captured_mails[0]
        self.assertEqual(rcpts, [user.email_address])
        msg = email.message_from_string(raw_msg)
        self.assertEqual(msg['To'], user.email_address)

        # headers and subject
        self.assertEqual(msg['X-Beaker-Notification'], 'group-membership')
        self.assertEqual(msg['X-Beaker-Group'], group.group_name)
        self.assertEqual(msg['X-Beaker-Group-Action'], action)
        for keyword in ['Group Membership', action, group.group_name]:
            self.assert_(keyword in msg['Subject'], msg['Subject'])

        # body
        msg_payload = msg.get_payload(decode=True)
        action = action.lower()
        for keyword in [action, group.group_name]:
            self.assert_(keyword in msg_payload, (keyword, msg_payload))

    def test_dictionary_password_rejected(self):
        b = self.browser
        login(b, user=self.user.user_name, password='password')
        self.go_to_group_page()
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]').click()
        modal = b.find_element_by_class_name('modal')
        modal.find_element_by_id('root_password').clear()
        modal.find_element_by_id('root_password').send_keys(self.simple_password)
        modal.find_element_by_tag_name('form').submit()
        self.assertIn('the password is based on a dictionary word',
                               modal.find_element_by_class_name('alert-error').text)

    def _update_root_password(self, password):
        b = self.browser
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]').click()
        modal = b.find_element_by_class_name('modal')
        modal.find_element_by_id('root_password').clear()
        modal.find_element_by_id('root_password').send_keys(password)
        modal.find_element_by_tag_name('form').submit()
        b.find_element_by_xpath('//body[not(.//div[contains(@class, "modal")])]')

    def test_set_hashed_password(self):
        b = self.browser
        login(b, user=self.user.user_name, password='password')
        self.go_to_group_page()
        self._update_root_password(self.hashed_password)
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]').click()
        modal = b.find_element_by_class_name('modal')
        new_hash = modal.find_element_by_id('root_password').get_attribute('value')
        self.failUnless(crypt.crypt(self.clear_password, new_hash) == self.hashed_password)

    def test_set_plaintext_password(self):
        b = self.browser
        login(b, user=self.user.user_name, password='password')
        self.go_to_group_page()
        self._update_root_password(self.clear_password)
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]').click()
        modal = b.find_element_by_class_name('modal')
        clear_pass = modal.find_element_by_id('root_password').get_attribute('value')
        self.assertEquals(clear_pass, self.clear_password)

        # check if the change has been recorded in the acitivity table
        with session.begin():
            self.assertEquals(self.group.activity[-1].action, u'Changed')
            self.assertEquals(self.group.activity[-1].field_name, u'Root Password')
            self.assertEquals(self.group.activity[-1].old_value, '*****')
            self.assertEquals(self.group.activity[-1].new_value, '*****')
            self.assertEquals(self.group.activity[-1].service, u'HTTP')

        # no change should be recorded if the same password is supplied
        group_activities = len([x for x in self.group.activity if
                                x.field_name == 'Root Password'])
        self.go_to_group_page()
        self._update_root_password(clear_pass)
        session.refresh(self.group)
        self.assertEquals(group_activities, len([x for x in self.group.activity if
                                                 x.field_name == 'Root Password']))

    #https://bugzilla.redhat.com/show_bug.cgi?id=1020091
    def test_password_visibility_members(self):
        b = self.browser
        login(b, user=self.user.user_name, password='password')
        self.go_to_group_page()
        self._update_root_password(self.clear_password)
        logout(b)

        # add a new user as a group member
        with session.begin():
            user = data_setup.create_user(password='password')
            self.group.add_member(user, is_owner=True)
        # login as the new user
        login(b, user=user.user_name, password='password')
        self.go_to_group_page()
        self.assertEquals(b.find_element_by_xpath("//div[@id='root_pw_display']/p").text,
                          "The group root password is: %s" % self.clear_password)

    #https://bugzilla.redhat.com/show_bug.cgi?id=1020091
    def test_password_not_set_visibility_members(self):
        b = self.browser
        # add a new user as a group member
        with session.begin():
            user = data_setup.create_user(password='password')
            user.groups.append(self.group)
        # login as the new user
        login(b, user=user.user_name, password='password')
        b.get(get_server_base() + 'groups/mine')
        b.find_element_by_link_text(self.group.group_name).click()
        self.assertEquals(b.find_element_by_xpath("//div[@id='root_pw_display']/p").text,
                          "No group root password set. "
                          "Group jobs will use the root password preferences of the submitting user.")

    def test_create_new_group(self):
        b = self.browser
        login(b, user=self.user.user_name, password='password')
        b.get(get_server_base() + 'groups/mine')
        b.find_element_by_link_text('Add').click()
        b.find_element_by_xpath('//input[@id="Group_display_name"]'). \
            send_keys('Group FBZ')
        b.find_element_by_xpath('//input[@id="Group_group_name"]'). \
            send_keys('FBZ')
        b.find_element_by_xpath('//input[@id="Group_root_password"]'). \
            send_keys('blapppy7')
        b.find_element_by_id('Group').submit()
        b.find_element_by_xpath('//title[text()="My Groups"]')
        b.find_element_by_link_text('FBZ').click()
        with session.begin():
            group = Group.by_name(u'FBZ')
            self.assertEquals(group.display_name, u'Group FBZ')
            self.assert_(group.has_owner(self.user))
            self.assertEquals(group.activity[-1].action, u'Added')
            self.assertEquals(group.activity[-1].field_name, u'Owner')
            self.assertEquals(group.activity[-1].new_value, self.user.user_name)
            self.assertEquals(group.activity[-1].service, u'WEBUI')
            self.assertEquals(group.activity[-2].action, u'Added')
            self.assertEquals(group.activity[-2].field_name, u'User')
            self.assertEquals(group.activity[-2].new_value, self.user.user_name)
            self.assertEquals(group.activity[-2].service, u'WEBUI')
            self.assertEquals(group.activity[-3].action, u'Created')
            self.assertEquals(group.activity[-3].service, u'WEBUI')
            self.assertEquals('blapppy7', group.root_password)

    def test_create_new_group_sans_password(self):
        b = self.browser
        group_name = data_setup.unique_name('group%s')
        login(b, user=self.user.user_name, password='password')
        b.get(get_server_base() + 'groups/mine')
        b.find_element_by_link_text('Add').click()
        b.find_element_by_xpath('//input[@id="Group_display_name"]'). \
            send_keys(group_name)
        b.find_element_by_xpath('//input[@id="Group_group_name"]'). \
            send_keys(group_name)
        b.find_element_by_id('Group').submit()
        b.find_element_by_xpath('//title[text()="My Groups"]')
        b.find_element_by_link_text(group_name).click()
        self.assertEquals(b.find_element_by_xpath("//div[@id='root_pw_display']/p").text,
              "No group root password set. "
              "Group jobs will use the root password preferences of the submitting user.")

    def test_can_edit_owned_group(self):
        b = self.browser
        login(b, user=self.user.user_name, password='password')
        self.go_to_group_page()
        self._update_root_password(u'blapppy7')
        session.expire(self.group)
        self.assertEquals('blapppy7', self.group.root_password)

    def test_cannot_edit_unowned_group(self):
        with session.begin():
            user = data_setup.create_user(password='password')
            self.group.add_member(user)
        b = self.browser
        login(b, user=user.user_name, password='password')
        self.go_to_group_page()
        b.find_element_by_xpath('//div[@id="group-details" and '
                'not(.//button[normalize-space(string(.))="Edit"])]')

    def test_add_user_to_owned_group(self):
        with session.begin():
            user = data_setup.create_user(password='password')

        b = self.browser
        login(b, user=self.user.user_name, password='password')
        b.get(get_server_base() + 'groups/mine')
        b.find_element_by_link_text('Add').click()
        b.find_element_by_xpath('//input[@id="Group_display_name"]'). \
            send_keys('Group FBZ 1')
        b.find_element_by_xpath('//input[@id="Group_group_name"]'). \
            send_keys('FBZ-1')
        b.find_element_by_id('Group').submit()
        b.find_element_by_xpath('//title[text()="My Groups"]')
        b.find_element_by_link_text('FBZ-1').click()

        b.find_element_by_xpath('//ul[contains(@class, "group-nav")]'
            '//a[text()="Members"]').click()
        b.find_element_by_name('group_member').send_keys(user.user_name)
        b.find_element_by_class_name('add-member').submit()
        b.find_element_by_xpath('//div/ul[@class="list-group group-members-list"]'
            '//li/a[contains(text(), "%s")]' % user.user_name)
        with session.begin():
            session.expire_all()
            group = Group.by_name('FBZ-1')
            self.assertIn(user, group.users)
        self.check_notification(user, group, action='Added')

    def test_remove_user_from_owned_group(self):
        with session.begin():
            user = data_setup.create_user(password='password')

        group_name = data_setup.unique_name('AAAAAA%s')
        display_name = data_setup.unique_name('Group Display Name %s')

        b = self.browser
        login(b, user=self.user.user_name, password='password')
        b.get(get_server_base() + 'groups/mine')
        b.find_element_by_link_text('Add').click()
        b.find_element_by_xpath('//input[@id="Group_display_name"]').send_keys(display_name)
        b.find_element_by_xpath('//input[@id="Group_group_name"]').send_keys(group_name)
        b.find_element_by_id('Group').submit()
        b.find_element_by_xpath('//title[text()="My Groups"]')
        b.find_element_by_link_text(group_name).click()

        # add an user
        b.find_element_by_xpath('//ul[contains(@class, "group-nav")]'
            '//a[text()="Members"]').click()
        b.find_element_by_name('group_member').send_keys(user.user_name)
        b.find_element_by_class_name('add-member').submit()
        b.find_element_by_xpath('//div/ul[@class="list-group group-members-list"]'
            '//li/a[contains(text(), "%s")]' % user.user_name)
        # clear captured mails
        self.mail_capture.captured_mails[:] = []
        b.find_element_by_xpath('//li[contains(a/text(), "%s")]/button' % user.user_name).click()
        b.find_element_by_xpath('//div/ul[@class="list-group group-members-list" and '
            'not(.//li/a[contains(text(), "%s")])]' % user.user_name)
        with session.begin():
            group = Group.by_name(group_name)
        self.check_notification(user, group, action='Removed')

        # remove self when I am the only owner of the group
        b.find_element_by_xpath('//li[contains(a/text(), "%s")]/button' % self.user.user_name).click()
        b.find_element_by_xpath('//div[contains(@class, "alert-error") and '
            'contains(string(.), "Cannot remove user %s from group %s")]' % (self.user.user_name, group_name))
        # admin should be able to remove an owner, even if only one
        logout(b)
        #login back as admin
        login(b)
        self.go_to_group_page(group, tab=u"Members")
        b.find_element_by_xpath('//li[contains(a/text(), "%s")]/button' % self.user.user_name).click()
        b.find_element_by_xpath('//div/ul[@class="list-group group-members-list" and '
            'not(.//li/a[contains(text(), "%s")])]' % self.user.user_name)

    #https://bugzilla.redhat.com/show_bug.cgi?id=966312
    def test_remove_self_admin_group(self):

        with session.begin():
            user = data_setup.create_admin(password='password')

        b = self.browser
        login(b, user=user.user_name, password='password')

        # admin should be in groups/mine
        b.get(get_server_base() + 'groups/mine')
        b.find_element_by_link_text('admin').click()

        # remove self
        b.find_element_by_xpath('//ul[contains(@class, "group-nav")]'
            '//a[text()="Members"]').click()
        b.find_element_by_xpath('//li[contains(a/text(), "%s")]/button' % user.user_name).click()
        b.find_element_by_xpath('//div/ul[@class="list-group group-members-list" and '
            'not(.//li/a[contains(text(), "%s")])]' % user.user_name)

        # admin should not be in groups/mine
        b.get(get_server_base() + 'groups/mine')
        check_group_search_results(b, absent=[Group.by_name(u'admin')])
        logout(b)

        # login as admin
        login(b)
        with session.begin():
            group = Group.by_name('admin')
            group_users = group.users
        # remove  all other users from 'admin'
        self.go_to_group_page(group, tab=u"Members")
        for usr in group_users:
            if usr.user_id != 1:
                b.find_element_by_xpath('//li[contains(a/text(), "%s")]/button' % usr.user_name).click()
                b.find_element_by_xpath('//div/ul[@class="list-group group-members-list" and '
                    'not(.//li/a[contains(text(), "%s")])]' % usr.user_name)

        # attempt to remove admin user
        b.find_element_by_xpath('//li[contains(a/text(), "%s")]/button' % data_setup.ADMIN_USER).click()
        b.find_element_by_xpath('//div[contains(@class, "alert-error") and '
            'contains(string(.), "Cannot remove user %s from group admin")]' % data_setup.ADMIN_USER)

    def test_removing_self_from_owned_group(self):
        """
        Removing self from an owned group will remove the privileges of editing the group,
        viewing the rootpassword, and modifying membership, ownership and permissions.
        """
        with session.begin():
            user = data_setup.create_user(password='password')
            another_user = data_setup.create_user()
            permission = data_setup.create_permission()
            group = data_setup.create_group(owner=user)
            group.add_member(another_user, is_owner=True)
            group.permissions.append(permission)

        b = self.browser
        login(b, user=user.user_name, password='password')
        self.go_to_group_page(group=group, tab=u'Members')
        b.find_element_by_xpath('//li[contains(a/text(), "%s")]/button' % user.user_name).click()
        b.find_element_by_xpath('//div/ul[@class="list-group group-members-list" and '
            'not(.//li/a[contains(text(), "%s")])]' % user.user_name)
        # Should not be able to edit
        b.find_element_by_xpath('//div[@id="group-details" and '
            'not(.//button[normalize-space(string(.))="Edit"])]')
        # should not be able to see the root password
        b.find_element_by_xpath('//div[@id="group-details" and '
            'not(.//div[@id="root_pw_display"]/p)]')
        # Should not be able to add/remove member
        b.find_element_by_xpath('//div[@id="members" and '
            'not(.//input[@name="group_member"])]')
        b.find_element_by_xpath('//ul[@class="list-group group-members-list" and '
            'not(.//button[contains(text(), "Remove")])]')
        # should not be able to add/remove owner
        b.find_element_by_xpath('//ul[contains(@class, "group-nav")]'
            '//a[text()="Owners"]').click()
        b.find_element_by_xpath('//div[@id="members" and '
            'not(.//input[@name="group_owner"])]')
        b.find_element_by_xpath('//ul[@class="list-group group-owners-list" and '
            'not(.//button[contains(text(), "Remove")])]')
        # should not be able to remove permission
        b.find_element_by_xpath('//ul[contains(@class, "group-nav")]'
            '//a[text()="Permissions"]').click()
        b.find_element_by_xpath('//ul[@class="list-group group-permissions-list" and '
            'not(.//button[contains(text(), "Remove")])]')

    def test_add_user_to_admin_group(self):
        with session.begin():
            user = data_setup.create_user(password='password')
            user.groups.append(Group.by_name('admin'))
            group = data_setup.create_group(group_name='aaaaaaaaaaaabcc')

        b = self.browser
        login(b, user=user.user_name, password='password')

        # admin should be in groups/mine
        b.get(get_server_base() + 'groups/mine')
        b.find_element_by_link_text('admin')

        # check if the user can edit any other group, when the user:
        # is not an owner
        # is not a member
        b.get(get_server_base() + 'groups/edit?group_id=%d' % group.group_id)
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]')

    def test_create_ldap_group(self):
        login(self.browser)
        b = self.browser
        b.get(get_server_base() + 'groups/new')
        b.find_element_by_name('group_name').send_keys('my_ldap_group')
        b.find_element_by_name('display_name').send_keys('My LDAP group')
        self.assertEquals(b.find_element_by_name('ldap').is_selected(), False)
        b.find_element_by_name('ldap').click()
        b.find_element_by_id('Group').submit()
        self.assertEquals(b.find_element_by_class_name('flash').text, 'OK')
        with session.begin():
            group = Group.by_name(u'my_ldap_group')
            self.assertEquals(group.ldap, True)
            self.assertEquals(group.users, [User.by_user_name(u'my_ldap_user')])

    def test_cannot_modify_membership_of_ldap_group(self):
        with session.begin():
            group = data_setup.create_group(ldap=True)
            group.add_member(data_setup.create_user())
        login(self.browser)
        b = self.browser
        self.go_to_group_page(group)
        # form to add new users should be absent
        b.find_element_by_xpath('//ul[contains(@class, "group-nav")]'
            '//a[text()="Members"]').click()
        b.find_element_by_xpath('//div[@id="members" and '
            'not(.//input[@name="group_member"])]')
        # "Remove" link should be absent from "User Members" list
        b.find_element_by_xpath('//ul[@class="list-group group-members-list" and '
            'not(.//button[contains(text(), "Remove")])]')

    def _edit_group_details(self, browser, new_group_name, new_display_name):
        b = browser
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]').click()
        modal = b.find_element_by_class_name('modal')
        modal.find_element_by_id('group_name').clear()
        modal.find_element_by_id('group_name').send_keys(new_group_name)
        modal.find_element_by_id('display_name').clear()
        modal.find_element_by_id('display_name').send_keys(new_display_name)
        modal.find_element_by_tag_name('form').submit()

    def test_edit_display_group_names(self):
        with session.begin():
            user = data_setup.create_user(password='password')
            group = data_setup.create_group(owner=user)

        b = self.browser
        login(b, user=user.user_name, password='password')

        new_display_name = 'New Display Name for Group FBZ 2'
        new_group_name = 'FBZ-2-new'

        # edit
        b.get(get_server_base() + 'groups/mine')
        b.find_element_by_link_text(group.group_name).click()
        self._edit_group_details(b, new_group_name, new_display_name)

        # check
        b.find_element_by_xpath('//body[not(.//div[contains(@class, "modal")])]')
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]').click()
        modal = b.find_element_by_class_name('modal')
        self.assertEquals(modal.find_element_by_id('group_name'). \
                              get_attribute('value'), new_group_name)
        self.assertEquals(modal.find_element_by_id('display_name'). \
                              get_attribute('value'), new_display_name)
        with session.begin():
            session.refresh(group)
            self.assertEquals(group.group_name, new_group_name)
            self.assertEquals(group.display_name, new_display_name)

    # https://bugzilla.redhat.com/show_bug.cgi?id=967799
    def test_edit_group_name_duplicate(self):
        with session.begin():
            user = data_setup.create_user(password='password')
            group1 = data_setup.create_group(owner=user)
            group2 = data_setup.create_group(owner=user)

        b = self.browser
        login(b, user=user.user_name, password='password')

        b.get(get_server_base() + 'groups/mine')
        b.find_element_by_link_text(group2.group_name).click()
        self._edit_group_details(b, group1.group_name, group2.display_name)
        self.assertIn('Group %s already exists' % group1.group_name,
                               b.find_element_by_class_name('alert-error').text)

    def test_cannot_rename_protected_group(self):
        with session.begin():
            admin_user = data_setup.create_admin(password='password')
            admin_group = Group.by_name(u'admin')
        b = self.browser

        login(b, user=admin_user.user_name, password='password')
        new_display_name = 'New Display Name for Group FBZ 2'
        new_group_name = 'FBZ-2-new'

        # edit
        b.get(get_server_base() + 'groups/edit?group_id=%d' % admin_group.group_id)
        self._edit_group_details(b, new_group_name, new_display_name)

        # check
        self.assertIn('Cannot rename protected group',
            b.find_element_by_class_name('alert-error').text)

    #https://bugzilla.redhat.com/show_bug.cgi?id=908174
    def test_add_remove_owner_group(self):
        with session.begin():
            user = data_setup.create_user(password='password')
            group = data_setup.create_group(owner=user)
            user1 = data_setup.create_user(password='password')

        b = self.browser
        login(b, user=user.user_name, password='password')
        b.get(get_server_base() + 'groups/mine')

        # remove self (as only owner)
        b.find_element_by_link_text(group.group_name).click()
        b.find_element_by_xpath('//ul[contains(@class, "group-nav")]'
            '//a[text()="Owners"]').click()
        b.find_element_by_xpath('//div/ul[@class="list-group group-owners-list"]'
            '/li[contains(a/text(), "%s")]/button' % user.user_name).click()
        b.find_element_by_xpath('//div[contains(@class, "alert-error") and contains(string(.), "Cannot remove the only owner")]')
        # add a new user as owner
        b.find_element_by_xpath('//ul[contains(@class, "group-nav")]'
            '//a[text()="Members"]').click()
        b.find_element_by_name('group_member').send_keys(user1.user_name)
        b.find_element_by_class_name('add-member').submit()
        b.find_element_by_xpath('//div/ul[@class="list-group group-members-list"]'
        '//li/a[contains(text(), "%s")]' % user1.user_name)
        # grant user1 the group ownership
        b.find_element_by_xpath('//ul[contains(@class, "group-nav")]'
            '//a[text()="Owners"]').click()
        b.find_element_by_name('group_owner').send_keys(user1.user_name)
        b.find_element_by_class_name('add-owner').submit()
        b.find_element_by_xpath('//div/ul[@class="list-group group-owners-list"]'
            '//li/a[contains(text(), "%s")]' % user1.user_name)
        logout(b)

        # login as the new user and check for ownership
        login(b, user=user1.user_name, password='password')
        b.get(get_server_base() + 'groups/mine')
        b.find_element_by_link_text(group.group_name).click()
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]')
        with session.begin():
            self.assertEquals(Activity.query.filter_by(service=u'HTTP',
                                                       field_name=u'Owner', action=u'Added',
                                                       new_value=user1.user_name).count(), 1)
            group = Group.by_name(group.group_name)
            self.assert_(group.has_owner(user1))
            self.assertEquals(group.activity[-1].action, u'Added')
            self.assertEquals(group.activity[-1].field_name, u'Owner')
            self.assertEquals(group.activity[-1].new_value, user1.user_name)
            self.assertEquals(group.activity[-1].service, u'HTTP')

        # remove self as owner
        b.find_element_by_xpath('//ul[contains(@class, "group-nav")]'
            '//a[text()="Owners"]').click()
        b.find_element_by_xpath('//div/ul[@class="list-group group-owners-list"]'
            '/li[contains(a/text(), "%s")]/button' % user1.user_name).click()
        b.find_element_by_xpath('//div/ul[@class="list-group group-owners-list" and '
            'not(.//li/a[contains(text(), "%s")])]' % user1.user_name)

        with session.begin():
            self.assertEquals(Activity.query.filter_by(service=u'HTTP',
                                                       field_name=u'Owner', action=u'Removed',
                                                       old_value=user1.user_name).count(), 1)
            session.refresh(group)
            self.assertEquals(group.activity[-1].action, u'Removed')
            self.assertEquals(group.activity[-1].field_name, u'Owner')
            self.assertEquals(group.activity[-1].old_value, user1.user_name)
            self.assertEquals(group.activity[-1].service, u'HTTP')

    #https://bugzilla.redhat.com/show_bug.cgi?id=990349
    #https://bugzilla.redhat.com/show_bug.cgi?id=990821
    def test_check_group_name_display_name_length(self):

        max_length_group_name = Group.group_name.property.columns[0].type.length
        max_length_disp_name = Group.display_name.property.columns[0].type.length

        b = self.browser
        login(b, user=self.user.user_name, password='password')

        # for new group
        b.get(get_server_base() + 'groups/mine')
        b.find_element_by_link_text('Add').click()
        b.find_element_by_xpath('//input[@id="Group_display_name"]'). \
            send_keys('A really long group display name'*20)
        b.find_element_by_xpath('//input[@id="Group_group_name"]'). \
            send_keys('areallylonggroupname'*20)
        b.find_element_by_id('Group').submit()
        error_text = b.find_element_by_xpath('//span[contains(@class, "error") '
                'and preceding-sibling::input/@name="group_name"]').text
        self.assertRegexpMatches(error_text,
                                 'Enter a value (less|not more) than %r characters long' % max_length_group_name)
        error_text = b.find_element_by_xpath('//span[contains(@class, "error") '
                'and preceding-sibling::input/@name="display_name"]').text
        self.assertRegexpMatches(error_text,
                                 'Enter a value (less|not more) than %r characters long' % max_length_disp_name)

        # modify existing group
        with session.begin():
            group = data_setup.create_group(owner=self.user)

        b.get(get_server_base() + 'groups/edit?group_id=%s' % group.group_id)
        new_name = 'areallylonggroupname'*20
        new_display_name = 'A really long group display name'*20
        self._edit_group_details(b, new_name, new_display_name)
        b.find_element_by_xpath('//body[not(.//div[contains(@class, "modal")])]')
        b.find_element_by_xpath('//title[normalize-space(text())="%s"]' % \
            new_name[:255])
        # A really long name will be truncated to 255 characters
        with session.begin():
            session.refresh(group)
            self.assertEqual(group.group_name, new_name[:255])
            self.assertEqual(group.display_name, new_display_name[:255])

    #https://bugzilla.redhat.com/show_bug.cgi?id=990860
    def test_show_group_owners(self):
        with session.begin():
            owner = data_setup.create_user(user_name='zzzz', password='password')
            group = data_setup.create_group(owner=owner)
            member1 = data_setup.create_user(user_name='aaaa', password='password')
            group.add_member(member1)
            member2 = data_setup.create_user(user_name='bbbb', password='password')
            group.add_member(member2)

        b = self.browser
        login(b, user=member1.user_name, password='password')
        # check group members list
        self.go_to_group_page(group, tab=u"Members")
        for user in [owner, member1, member2]:
            b.find_element_by_xpath('//div/ul[@class="list-group group-members-list"]'
                '/li[contains(a/text(), "%s")]' % user.user_name)
        # check group owners list
        self.go_to_group_page(group, tab=u"Owners")
        b.find_element_by_xpath('//div/ul[@class="list-group group-owners-list"]'
            '/li[contains(a/text(), "%s")]' % owner.user_name)
        for user in [member1, member2]:
            b.find_element_by_xpath('//div/ul[@class="list-group group-owners-list" and '
                'not(.//li[contains(a/text(), "%s")])]' % user.user_name)

    def test_visit_edit_page_with_group_id_or_name(self):
        with session.begin():
            user = data_setup.create_user(password='password')
            group = data_setup.create_group(owner=user)

        b = self.browser
        login(b, user=user.user_name, password='password')

        b.get(get_server_base() + 'groups/edit?group_id=%s' % group.group_id)
        b.find_element_by_xpath('//title[normalize-space(text())="%s"]' % \
            group.group_name)
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]')

        b.get(get_server_base() + 'groups/edit?group_name=%s' % group.group_name)
        b.find_element_by_xpath('//title[normalize-space(text())="%s"]' % \
            group.group_name)
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]')

    # https://bugzilla.redhat.com/show_bug.cgi?id=1102617
    def test_cannot_delete_protected_group_by_admin(self):
        with session.begin():
            user = data_setup.create_admin(password='password')
            admin_group = Group.by_name('admin')
        b = self.browser
        login(b, user=user.user_name, password='password')
        b.get(get_server_base() + 'groups/')
        self.assert_('Delete' not in b.find_element_by_xpath("//tr[(td[1]/a[text()='%s'])]"
                                                    % admin_group.group_name).text)
        b.get(get_server_base() + 'groups/mine')
        self.assert_('Delete' not in b.find_element_by_xpath("//tr[(td[1]/a[text()='%s'])]"
                                                    % admin_group.group_name).text)

    def test_cannot_update_group_with_empty_name(self):
        b = self.browser
        login(b, user=self.user.user_name, password='password')
        self.go_to_group_page()
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]').click()
        modal = b.find_element_by_class_name('modal')
        modal.find_element_by_xpath('//input[@id="group_name"]').clear()
        modal.find_element_by_xpath('//input[@id="group_name"]').\
            send_keys('')
        modal.find_element_by_tag_name('form').submit()
        self.assertTrue(b.find_element_by_css_selector('input[name="group_name"]:required:invalid'))

    def test_cannot_update_group_with_empty_display_name(self):
        b = self.browser
        login(b, user=self.user.user_name, password='password')
        self.go_to_group_page()
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]').click()
        modal = b.find_element_by_class_name('modal')
        modal.find_element_by_xpath('//input[@id="display_name"]').clear()
        modal.find_element_by_xpath('//input[@id="display_name"]').\
            send_keys('')
        modal.find_element_by_tag_name('form').submit()
        self.assertTrue(b.find_element_by_css_selector('input[name="display_name"]:required:invalid'))


class GroupHTTPTest(DatabaseTestCase):
    """
    Directly tests the HTTP interface used by the group editing page.
    """
    def setUp(self):
        with session.begin():
            self.user = data_setup.create_user(password=u'password')
            self.group = data_setup.create_group(owner=self.user)

    def test_get_group(self):
        response = requests.get(get_server_base() +
                'groups/%s' % self.group.group_name, headers={'Accept': 'application/json'})
        response.raise_for_status()
        json = response.json()
        self.assertEquals(json['id'], self.group.id)
        self.assertEquals(json['group_name'], self.group.group_name)
        self.assertEquals(json['display_name'], self.group.display_name)

    def test_update_group(self):
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                                                  'password': u'password'}).raise_for_status()
        response = patch_json(get_server_base() +
                'groups/%s' % self.group.group_name, session=s,
                data={'group_name': u'newname',
                      'display_name': u'newdisplayname',
                      'root_password': u'$1$NaCl$O34mAzBXtER6obhoIodu8.'})
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertEquals(self.group.group_name, u'newname')
            self.assertEquals(self.group.display_name, u'newdisplayname')
            self.assertEquals(self.group.root_password, u'$1$NaCl$O34mAzBXtER6obhoIodu8.')

    def test_cannot_update_group_with_empty_name_or_display_name(self):
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                                                  'password': u'password'}).raise_for_status()
        response = patch_json(get_server_base() +
                'groups/%s' % self.group.group_name, session=s,
                data={'group_name': ''})
        self.assertEqual(400, response.status_code)
        self.assertEqual('Group name cannot be empty', response.text)
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                                                  'password': u'password'}).raise_for_status()
        response = patch_json(get_server_base() +
                'groups/%s' % self.group.group_name, session=s,
                data={'display_name': ''})
        self.assertEqual(400, response.status_code)
        self.assertEqual('Group display name cannot be empty', response.text)

    def test_cannot_update_group_with_leading_space_or_trailing_space(self):
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                                                  'password': u'password'}).raise_for_status()
        response = patch_json(get_server_base() +
                'groups/%s' % self.group.group_name, session=s,
                data={'group_name': u' new name '})
        self.assertEqual(400, response.status_code)
        self.assertEqual('Group name must not contain leading or trailing whitespace',
                          response.text)

        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                                                  'password': u'password'}).raise_for_status()
        response = patch_json(get_server_base() +
                'groups/%s' % self.group.group_name, session=s,
                data={'display_name': u' new display name '})
        self.assertEqual(400, response.status_code)
        self.assertEqual('Group display name must not contain leading or trailing whitespace',
                          response.text)

    def test_unauthenticated_user_cannot_add_permission(self):
        with session.begin():
            permission = data_setup.create_permission()
        s = requests.Session()
        response = post_json(get_server_base() + 'groups/%s/permissions/' % self.group.group_name,
                session=s, data={'permission_name': permission.permission_name})
        self.assertEquals(response.status_code, 401)
        self.assertEquals(response.text, 'Authenticated user required')

    def test_non_admin_cannot_add_permission(self):
        with session.begin():
            permission = data_setup.create_permission()
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                'password': u'password'}).raise_for_status()
        response = post_json(get_server_base() + 'groups/%s/permissions/' % self.group.group_name,
                session=s, data={'permission_name': permission.permission_name})
        self.assertEquals(response.status_code, 403)
        self.assertIn('You are not a member of the admin group', response.text)

    def test_admin_can_add_permssion(self):
        with session.begin():
           permission = data_setup.create_permission()
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': data_setup.ADMIN_USER,
               'password': data_setup.ADMIN_PASSWORD}).raise_for_status()
        response = post_json(get_server_base() + 'groups/%s/permissions/' % self.group.group_name,
               session=s, data={'permission_name': permission.permission_name})
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertItemsEqual(self.group.permissions, [permission])
            self.assertEquals(self.group.activity[-1].field_name, 'Permission')
            self.assertEquals(self.group.activity[-1].action, 'Added')
            self.assertEquals(self.group.activity[-1].new_value, unicode(permission))\

    def test_adding_permission_to_nonexistent_group_raises_an_error(self):
        with session.begin():
           permission = data_setup.create_permission()
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': data_setup.ADMIN_USER,
               'password': data_setup.ADMIN_PASSWORD}).raise_for_status()
        response = post_json(get_server_base() + 'groups/nosuchgroup/permissions/',
                session=s, data={'permission_name': permission.permission_name})
        self.assertEquals(response.status_code, 404)
        self.assertEquals(response.text, 'Group nosuchgroup does not exist')

    def test_adding_nonexistent_permission_raises_an_error(self):
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': data_setup.ADMIN_USER,
               'password': data_setup.ADMIN_PASSWORD}).raise_for_status()
        response = post_json(get_server_base() + 'groups/%s/permissions/' % self.group.group_name,
                session=s, data={'permission_name': 'nosuchpermission'})
        self.assertEquals(response.status_code, 400)
        self.assertEquals(response.text, "Permission 'nosuchpermission' does not exist")

    def test_unauthenticated_user_cannot_remove_permission(self):
        with session.begin():
            permission = data_setup.create_permission()
            self.group.permissions.append(permission)
        s = requests.Session()
        response = s.delete(get_server_base() +
            'groups/%s/permissions?permission_name=%s' % (self.group.group_name,
                                                  permission.permission_name))
        self.assertEquals(response.status_code, 401)
        self.assertEquals(response.text, 'Authenticated user required')

    def test_can_remove_permission(self):
        with session.begin():
            permission = data_setup.create_permission()
            self.group.permissions.append(permission)
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                                                  'password': u'password'}).raise_for_status()
        response = s.delete(get_server_base() +
            'groups/%s/permissions?permission_name=%s' % (self.group.group_name,
                                                  permission.permission_name))
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertNotIn(permission, self.group.permissions)
            self.assertEquals(self.group.activity[-1].field_name, 'Permission')
            self.assertEquals(self.group.activity[-1].action, 'Removed')
            self.assertEquals(self.group.activity[-1].old_value, unicode(permission))

    def test_non_group_owner_cannot_modify_membership(self):
        with session.begin():
            user = data_setup.create_user(password=u'password')
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': user.user_name,
                                                  'password': u'password'}).raise_for_status()
        response = post_json(get_server_base() + 'groups/%s/members/' % self.group.group_name,
                session=s, data={'user': user.user_name})
        self.assertEquals(response.status_code, 403)
        self.assertIn('Cannot edit group', response.text)

    def test_cannot_add_member_to_ldap_group(self):
        with session.begin():
            user = data_setup.create_user(password=u'password')
            ldap_group = data_setup.create_group(ldap=True)
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': data_setup.ADMIN_USER,
                                                  'password': data_setup.ADMIN_PASSWORD}).raise_for_status()
        response = post_json(get_server_base() + 'groups/%s/members/' % ldap_group.group_name,
                session=s, data={'user_name': user.user_name})
        self.assertEquals(response.status_code, 403)
        self.assertIn("Cannot edit membership of LDAP group %s" %
                                ldap_group.group_name, response.text)

    def test_can_add_member(self):
        with session.begin():
            user = data_setup.create_user(password=u'password')
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                'password': u'password'}).raise_for_status()
        response = post_json(get_server_base() + 'groups/%s/members/' % self.group.group_name,
                session=s, data={'user_name': user.user_name, 'is_owner': True})
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertIn(user, self.group.users)
            self.assertTrue(self.group.has_owner(user))
            self.assertEquals(self.group.activity[-1].user, self.user)
            self.assertEquals(self.group.activity[-1].field_name, 'Owner')
            self.assertEquals(self.group.activity[-1].action, 'Added')
            self.assertEquals(self.group.activity[-1].new_value, unicode(user))
            self.assertEquals(self.group.activity[-2].user, self.user)
            self.assertEquals(self.group.activity[-2].field_name, 'User')
            self.assertEquals(self.group.activity[-2].action, 'Added')
            self.assertEquals(self.group.activity[-2].new_value, unicode(user))

    def test_can_remove_member(self):
        with session.begin():
            user = data_setup.create_user()
            self.group.add_member(user)
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                                                  'password': u'password'}).raise_for_status()
        response = s.delete(get_server_base() +
            'groups/%s/members/?user_name=%s' % (self.group.group_name, user.user_name))
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertNotIn(user, self.group.users)
            self.assertEquals(self.group.activity[-1].user, self.user)
            self.assertEquals(self.group.activity[-1].field_name, 'User')
            self.assertEquals(self.group.activity[-1].action, 'Removed')
            self.assertEquals(self.group.activity[-1].old_value, unicode(user))

    def test_cannot_modify_ownership_on_unowned_group(self):
        with session.begin():
            user = data_setup.create_user(password=u'password')
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': user.user_name,
                                                  'password': u'password'}).raise_for_status()
        response = post_json(get_server_base() + 'groups/%s/owners/' % self.group.group_name,
                session=s, data={'user_name': user.user_name})
        self.assertEquals(response.status_code, 403)
        self.assertIn('Cannot edit group', response.text)

    def test_cannot_grant_LDAP_group_ownership_to_non_group_member(self):
        """
        Cannot give the ownership of LDAP group to a user who is not a member.
        """
        with session.begin():
            user = data_setup.create_user(password=u'password')
            ldap_group = data_setup.create_group(ldap=True)
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': data_setup.ADMIN_USER,
                                                  'password': data_setup.ADMIN_PASSWORD}). \
                                                   raise_for_status()
        response = post_json(get_server_base() + 'groups/%s/owners/' % ldap_group.group_name,
                session=s, data={'user_name': user.user_name})
        self.assertEquals(response.status_code, 400)
        self.assertIn("User %s is not a member of LDAP group %s" %
            (user.user_name, ldap_group.group_name), response.text)

    def test_can_grant_ownership_to_group_member(self):
        with session.begin():
            user = data_setup.create_user(password=u'password')
            self.group.add_member(user)
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                'password': u'password'}).raise_for_status()
        response = post_json(get_server_base() + 'groups/%s/owners/' % self.group.group_name,
                session=s, data={'user_name': user.user_name})
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertTrue(self.group.has_owner(user))
            self.assertEquals(self.group.activity[-1].user, self.user)
            self.assertEquals(self.group.activity[-1].field_name, 'Owner')
            self.assertEquals(self.group.activity[-1].action, 'Added')
            self.assertEquals(self.group.activity[-1].new_value, unicode(user))

    def test_can_grant_ownership_to_non_group_member(self):
        with session.begin():
            user = data_setup.create_user()
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                'password': u'password'}).raise_for_status()
        response = post_json(get_server_base() + 'groups/%s/owners/' % self.group.group_name,
                session=s, data={'user_name': user.user_name})
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertIn(user, self.group.users)
            self.assertTrue(self.group.has_owner(user))
            self.assertEquals(self.group.activity[-1].user, self.user)
            self.assertEquals(self.group.activity[-1].field_name, 'Owner')
            self.assertEquals(self.group.activity[-1].action, 'Added')
            self.assertEquals(self.group.activity[-1].new_value, unicode(user))
            self.assertEquals(self.group.activity[-2].user, self.user)
            self.assertEquals(self.group.activity[-2].field_name, 'User')
            self.assertEquals(self.group.activity[-2].action, 'Added')
            self.assertEquals(self.group.activity[-2].new_value, unicode(user))

    def test_can_revoke_ownership(self):
        with session.begin():
            user = data_setup.create_user()
            self.group.add_member(user, is_owner=True)
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': self.user.user_name,
                                                  'password': u'password'}).raise_for_status()
        response = s.delete(get_server_base() +
            'groups/%s/owners/?user_name=%s' % (self.group.group_name, user.user_name))
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertFalse(self.group.has_owner(user))
            self.assertIn(user, self.group.users)
            self.assertEquals(self.group.activity[-1].user, self.user)
            self.assertEquals(self.group.activity[-1].field_name, 'Owner')
            self.assertEquals(self.group.activity[-1].action, 'Removed')
            self.assertEquals(self.group.activity[-1].old_value, unicode(user))

    def test_cannot_remove_the_only_owner(self):
        """
        User without admin permission cannot remove the only owner of a group.
        """
        with session.begin():
            user = data_setup.create_user(password=u'password')
            group = data_setup.create_group(owner=user)
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': user.user_name,
                                                  'password': u'password'}).raise_for_status()
        response = s.delete(get_server_base() +
            'groups/%s/owners/?user_name=%s' % (group.group_name, user.user_name))
        self.assertEquals(response.status_code, 403)
        self.assertIn('Cannot remove the only owner', response.text)

    def test_can_remove_the_only_owner_by_admin(self):
        with session.begin():
            user = data_setup.create_user(password=u'password')
            group = data_setup.create_group(owner=user)
        s = requests.Session()
        s.post(get_server_base() + 'login', data={'user_name': data_setup.ADMIN_USER,
            'password': data_setup.ADMIN_PASSWORD}).raise_for_status()
        response = s.delete(get_server_base() +
            'groups/%s/owners/?user_name=%s' % (group.group_name, user.user_name))
        with session.begin():
            session.refresh(group)
            self.assertFalse(group.has_owner(user))
            self.assertEqual(group.owners(), [])
