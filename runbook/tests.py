from django.test import TestCase, Client, RequestFactory
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient
from unittest import mock

from runbook.models import Runbook, RunbookExecution, ScheduledJob
from runbook.views import execution_start
from runbook.management.commands.startscheduler import run_scheduled_job


class DisabledRunbookExecutionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owner', password='testpass123')
        self.disabled_runbook = Runbook.objects.create(
            name='Disabled Runbook',
            owner=self.user,
            is_active=False,
        )
        self.active_runbook = Runbook.objects.create(
            name='Active Runbook',
            owner=self.user,
            is_active=True,
        )

    @mock.patch('runbook.views.ExecutionEngine.run')
    def test_web_view_blocks_disabled_runbook_by_owner(self, mock_engine_run):
        """Owner with a disabled runbook should get an error when trying to run via the web UI."""
        self.client.force_login(self.user)
        url = reverse('execution_start', kwargs={'runbook_id': self.disabled_runbook.pk})
        response = self.client.post(url)

        self.assertRedirects(response, reverse('runbook_list'))
        self.assertEqual(RunbookExecution.objects.filter(runbook=self.disabled_runbook).count(), 0)
        mock_engine_run.assert_not_called()

    @mock.patch('runbook.views.ExecutionEngine.run')
    def test_web_view_allows_active_runbook(self, mock_engine_run):
        """Owner should be able to run an active runbook via the web UI."""
        self.client.force_login(self.user)
        url = reverse('execution_start', kwargs={'runbook_id': self.active_runbook.pk})
        response = self.client.post(url)

        self.assertEqual(RunbookExecution.objects.filter(runbook=self.active_runbook).count(), 1)
        mock_engine_run.assert_called_once()

    @mock.patch('runbook.views.ExecutionEngine.run')
    def test_api_blocks_disabled_runbook_by_owner(self, mock_engine_run):
        """Owner with a disabled runbook should get a 400 Bad Request via the API."""
        api_client = APIClient()
        api_client.force_authenticate(user=self.user)
        url = reverse('runbook-start', kwargs={'pk': self.disabled_runbook.pk})
        response = api_client.post(url)

        self.assertEqual(response.status_code, 400)
        self.assertIn('disabled', response.data['detail'].lower())
        self.assertEqual(RunbookExecution.objects.filter(runbook=self.disabled_runbook).count(), 0)
        mock_engine_run.assert_not_called()

    @mock.patch('runbook.views.ExecutionEngine.run')
    def test_api_allows_active_runbook(self, mock_engine_run):
        """Owner should be able to run an active runbook via the API."""
        api_client = APIClient()
        api_client.force_authenticate(user=self.user)
        url = reverse('runbook-start', kwargs={'pk': self.active_runbook.pk})
        response = api_client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(RunbookExecution.objects.filter(runbook=self.active_runbook).count(), 1)
        mock_engine_run.assert_called_once()

    @mock.patch('runbook.management.commands.startscheduler.ExecutionEngine.run')
    def test_scheduler_skips_disabled_runbook(self, mock_engine_run):
        """Scheduler should skip execution when the linked runbook is disabled."""
        scheduled_job = ScheduledJob.objects.create(
            runbook=self.disabled_runbook,
            cron_expression='0 0 * * *',
            is_active=True,
            created_by=self.user,
        )

        run_scheduled_job(scheduled_job.pk)

        self.assertEqual(RunbookExecution.objects.filter(runbook=self.disabled_runbook).count(), 0)
        mock_engine_run.assert_not_called()

    @mock.patch('runbook.management.commands.startscheduler.ExecutionEngine.run')
    def test_scheduler_runs_active_runbook(self, mock_engine_run):
        """Scheduler should execute when the linked runbook is active."""
        scheduled_job = ScheduledJob.objects.create(
            runbook=self.active_runbook,
            cron_expression='0 0 * * *',
            is_active=True,
            created_by=self.user,
        )

        run_scheduled_job(scheduled_job.pk)

        self.assertEqual(RunbookExecution.objects.filter(runbook=self.active_runbook).count(), 1)
        mock_engine_run.assert_called_once()
