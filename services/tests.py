import json
import uuid
import responses

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token

from .models import Status, Service, UserServiceToken
from .tasks import poll_service


class APITestCase(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.adminclient = APIClient()


class AuthenticatedAPITestCase(APITestCase):

    def setUp(self):
        super(AuthenticatedAPITestCase, self).setUp()
        self.username = 'testuser'
        self.password = 'testpass'
        self.user = User.objects.create_user(self.username,
                                             'testuser@example.com',
                                             self.password)
        token = Token.objects.create(user=self.user)
        self.token = token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

        # Admin User setup
        self.adminusername = 'testadminuser'
        self.adminpassword = 'testadminpass'
        self.adminuser = User.objects.create_superuser(
            self.adminusername,
            'testadminuser@example.com',
            self.adminpassword)
        admintoken = Token.objects.create(user=self.adminuser)
        self.admintoken = admintoken.key
        self.adminclient.credentials(
            HTTP_AUTHORIZATION='Token ' + self.admintoken)
        self.primary_service = self.make_service()


class TestServicesApp(AuthenticatedAPITestCase):

    def make_service(self, service_data=None):
        if service_data is None:
            service_data = {
                "name": "Test Service",
                "url": "http://example.org",
                "token": str(uuid.uuid4()),
                "up": True
            }
        service = Service.objects.create(**service_data)
        return service

    def make_status(self, status_data=None):
        if status_data is None:
            status_data = {
                "service": self.primary_service,
                "up": True
            }
        status = Status.objects.create(**status_data)
        return status

    def make_user_service_token(self, user_id, service):
        user_service_token = {
            "user_id": user_id,
            "email": "%s@example.org" % user_id,
            "service": service,
            "token": str(uuid.uuid4())
        }
        token = UserServiceToken.objects.create(**user_service_token)
        return token

    def test_login(self):
        request = self.client.post(
            '/api/token-auth/',
            {"username": "testuser", "password": "testpass"})
        token = request.data.get('token', None)
        self.assertIsNotNone(
            token, "Could not receive authentication token on login post.")
        self.assertEqual(request.status_code, 200,
                         "Status code on /api/token-auth was %s -should be 200"
                         % request.status_code)

    def test_create_service_model_data(self):
        token = str(uuid.uuid4())
        post_data = {
            "name": "API Created Service",
            "url": "http://api.example.org",
            "token": token
        }
        response = self.client.post('/api/v1/service/',
                                    json.dumps(post_data),
                                    content_type='application/json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        d = Service.objects.get(id=response.json()["id"])
        self.assertEqual(d.name, 'API Created Service')
        self.assertEqual(d.url, 'http://api.example.org')
        self.assertEqual(d.token, token)
        self.assertEqual(d.up, False)
        self.assertEqual(d.created_by, self.user)

    def test_create_status_model_data_blocked(self):
        post_data = {
            "service": str(self.primary_service.id),
            "up": True
        }
        response = self.client.post('/api/v1/status/',
                                    json.dumps(post_data),
                                    content_type='application/json')

        self.assertEqual(response.status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_list_status_unfiltered(self):
        self.make_status()
        self.make_status()

        response = self.client.get('/api/v1/status/',
                                   content_type='application/json')

        self.assertEqual(response.status_code,
                         status.HTTP_200_OK)

        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["up"], True)
        self.assertEqual(results[1]["up"], True)

    def test_list_status_filtered_service(self):
        self.make_status()
        service2 = self.make_service(service_data={
            "name": "Service 2",
            "url": "http://2.example.org",
            "token": str(uuid.uuid4())
        })
        self.make_status(status_data={
            "service": service2,
            "up": False
        })

        response = self.client.get('/api/v1/status/',
                                   {"service": str(service2.id)},
                                   content_type='application/json')

        self.assertEqual(response.status_code,
                         status.HTTP_200_OK)

        results = response.json()["results"]
        self.assertEqual(Status.objects.all().count(), 2)  # two in DB
        self.assertEqual(len(results), 1)  # one in filtered response
        self.assertEqual(results[0]["up"], False)

    def test_list_status_filtered_status(self):
        self.make_status()
        service2 = self.make_service(service_data={
            "name": "Service 2",
            "url": "http://2.example.org",
            "token": str(uuid.uuid4())
        })
        self.make_status(status_data={
            "service": service2,
            "up": False
        })
        self.make_status(status_data={
            "service": service2,
            "up": True
        })

        response = self.client.get('/api/v1/status/',
                                   {"up": "True"},  # this is boolean in GET
                                   content_type='application/json')

        self.assertEqual(response.status_code,
                         status.HTTP_200_OK)

        results = response.json()["results"]
        self.assertEqual(Status.objects.all().count(), 3)  # two in DB
        self.assertEqual(len(results), 2)  # two in filtered response
        # from different services
        self.assertNotEqual(results[0]["service"], results[1]["service"])

    def test_list_user_service_token_filtered_user_id(self):
        service2 = self.make_service(service_data={
            "name": "Service 2",
            "url": "http://2.example.org",
            "token": str(uuid.uuid4())
        })
        self.make_user_service_token(user_id=1, service=self.primary_service)
        self.make_user_service_token(user_id=1, service=service2)
        self.make_user_service_token(user_id=2, service=self.primary_service)

        response = self.client.get('/api/v1/userservicetoken/',
                                   {"user_id": 1},
                                   content_type='application/json')

        self.assertEqual(response.status_code,
                         status.HTTP_200_OK)

        results = response.json()["results"]
        self.assertEqual(UserServiceToken.objects.all().count(), 3)  # 3 in DB
        self.assertEqual(len(results), 2)  # two in filtered response
        # from different services
        self.assertNotEqual(results[0]["service"], results[1]["service"])

    def test_list_user_service_token_filtered_email(self):
        service2 = self.make_service(service_data={
            "name": "Service 2",
            "url": "http://2.example.org",
            "token": str(uuid.uuid4())
        })
        self.make_user_service_token(user_id=1, service=self.primary_service)
        self.make_user_service_token(user_id=1, service=service2)
        self.make_user_service_token(user_id=2, service=self.primary_service)

        response = self.client.get('/api/v1/userservicetoken/',
                                   {"email": "2@example.org"},
                                   content_type='application/json')

        self.assertEqual(response.status_code,
                         status.HTTP_200_OK)

        results = response.json()["results"]
        self.assertEqual(UserServiceToken.objects.all().count(), 3)  # 3 in DB
        self.assertEqual(len(results), 1)  # one in filtered response
        # from different services
        self.assertEqual(results[0]["email"], "2@example.org")

    @responses.activate
    def test_task_service_poll_404(self):
        # Setup
        # mock identity lookup
        responses.add(
            responses.GET,
            'http://example.org/api/health',
            body='<h1>404 File Not Found</h1>',
            status=404, content_type='application/json',
        )

        # Execute
        result = poll_service.apply_async(
            kwargs={
                "service_id": str(self.primary_service.id)
            })

        # Check
        self.assertEqual(
            result.get(),
            "Completed healthcheck for <Test Service>")
        updated = Service.objects.get(id=str(self.primary_service.id))
        self.assertEqual(updated.up, False)
        status = Status.objects.last()
        self.assertEqual(Status.objects.all().count(), 1)
        self.assertEqual(status.result["error"],
                         "No parseable response from service")

    @responses.activate
    def test_task_service_poll_down(self):
        # Setup
        # mock identity lookup
        responses.add(
            responses.GET,
            'http://example.org/api/health',
            json={
                "up": False,
                "result": {
                    "database": "No connection could be made"
                }
            },
            status=200, content_type='application/json',
        )

        # Execute
        result = poll_service.apply_async(
            kwargs={
                "service_id": str(self.primary_service.id)
            })

        # Check
        self.assertEqual(
            result.get(),
            "Completed healthcheck for <Test Service>")
        updated = Service.objects.get(id=str(self.primary_service.id))
        self.assertEqual(updated.up, False)
        status = Status.objects.last()
        self.assertEqual(Status.objects.all().count(), 1)
        self.assertEqual(status.up, False)
        self.assertEqual(status.result["database"],
                         "No connection could be made")

    @responses.activate
    def test_task_service_poll_up(self):
        # Setup
        # mock identity lookup
        responses.add(
            responses.GET,
            'http://example.org/api/health',
            json={
                "up": True,
                "result": {
                    "database": "Response in <0.1> seconds"
                }
            },
            status=200, content_type='application/json',
        )

        # Execute
        result = poll_service.apply_async(
            kwargs={
                "service_id": str(self.primary_service.id)
            })

        # Check
        self.assertEqual(
            result.get(),
            "Completed healthcheck for <Test Service>")
        updated = Service.objects.get(id=str(self.primary_service.id))
        self.assertEqual(updated.up, True)
        status = Status.objects.last()
        self.assertEqual(Status.objects.all().count(), 1)
        self.assertEqual(status.up, True)
        self.assertEqual(status.result["database"],
                         "Response in <0.1> seconds")
