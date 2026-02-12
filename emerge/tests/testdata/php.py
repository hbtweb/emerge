# PHP test data for parser testing

PHP_TEST_FILES = {"UserRepository.php": """<?php
/*
 * User Repository
 * Handles database operations for users
 */

namespace App\\Repositories;

use PDO;
use App\\Models\\User;
use App\\Contracts\\RepositoryInterface;
use App\\Exceptions\\UserNotFoundException;

class UserRepository implements RepositoryInterface
{
    private PDO $pdo;

    public function __construct(PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    public function findById(int $id): ?User
    {
        $stmt = $this->pdo->prepare('SELECT * FROM users WHERE id = :id');
        $stmt->execute(['id' => $id]);
        $data = $stmt->fetch(PDO::FETCH_ASSOC);

        if (!$data) {
            throw new UserNotFoundException("User not found: {$id}");
        }

        return new User($data);
    }

    public function findAll(): array
    {
        $stmt = $this->pdo->query('SELECT * FROM users');
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }

    public function save(User $user): bool
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO users (name, email) VALUES (:name, :email)'
        );
        return $stmt->execute([
            'name' => $user->getName(),
            'email' => $user->getEmail()
        ]);
    }
}
""", "UserService.php": """<?php

namespace App\\Services;

use App\\Repositories\\UserRepository;
use App\\Models\\User;
use App\\Events\\UserCreated;

class UserService
{
    private UserRepository $repository;

    public function __construct(UserRepository $repository)
    {
        $this->repository = $repository;
    }

    public function getUser(int $id): ?User
    {
        return $this->repository->findById($id);
    }

    public function createUser(array $data): User
    {
        $user = new User($data);
        $this->repository->save($user);
        event(new UserCreated($user));
        return $user;
    }

    public function getAllUsers(): array
    {
        return $this->repository->findAll();
    }
}
""", "User.php": """<?php

namespace App\\Models;

use App\\Contracts\\ModelInterface;

class User implements ModelInterface
{
    private ?int $id;
    private string $name;
    private string $email;
    private ?string $createdAt;

    public function __construct(array $data = [])
    {
        $this->id = $data['id'] ?? null;
        $this->name = $data['name'] ?? '';
        $this->email = $data['email'] ?? '';
        $this->createdAt = $data['created_at'] ?? null;
    }

    public function getId(): ?int
    {
        return $this->id;
    }

    public function getName(): string
    {
        return $this->name;
    }

    public function getEmail(): string
    {
        return $this->email;
    }

    public function toArray(): array
    {
        return [
            'id' => $this->id,
            'name' => $this->name,
            'email' => $this->email,
            'created_at' => $this->createdAt,
        ];
    }
}
""", "AbstractController.php": """<?php

namespace App\\Http\\Controllers;

use App\\Http\\Request;
use App\\Http\\Response;

abstract class AbstractController
{
    protected Request $request;
    protected Response $response;

    public function __construct(Request $request, Response $response)
    {
        $this->request = $request;
        $this->response = $response;
    }

    abstract public function index(): Response;

    protected function json(array $data, int $status = 200): Response
    {
        return $this->response->json($data, $status);
    }

    protected function validate(array $rules): array
    {
        return $this->request->validate($rules);
    }
}
""", "UserController.php": """<?php

namespace App\\Http\\Controllers;

use App\\Services\\UserService;
use App\\Http\\Request;
use App\\Http\\Response;

final class UserController extends AbstractController
{
    private UserService $userService;

    public function __construct(
        Request $request,
        Response $response,
        UserService $userService
    ) {
        parent::__construct($request, $response);
        $this->userService = $userService;
    }

    public function index(): Response
    {
        $users = $this->userService->getAllUsers();
        return $this->json(['users' => $users]);
    }

    public function show(int $id): Response
    {
        $user = $this->userService->getUser($id);
        return $this->json(['user' => $user->toArray()]);
    }

    public function store(): Response
    {
        $data = $this->validate([
            'name' => 'required|string',
            'email' => 'required|email'
        ]);

        $user = $this->userService->createUser($data);
        return $this->json(['user' => $user->toArray()], 201);
    }
}
""", "RepositoryInterface.php": """<?php

namespace App\\Contracts;

interface RepositoryInterface
{
    public function findById(int $id);
    public function findAll(): array;
    public function save($entity): bool;
}
""", "CacheableTrait.php": """<?php

namespace App\\Traits;

use App\\Services\\CacheService;

trait CacheableTrait
{
    protected ?CacheService $cacheService = null;

    public function setCacheService(CacheService $cacheService): void
    {
        $this->cacheService = $cacheService;
    }

    protected function remember(string $key, int $ttl, callable $callback)
    {
        if ($this->cacheService === null) {
            return $callback();
        }

        $cached = $this->cacheService->get($key);
        if ($cached !== null) {
            return $cached;
        }

        $result = $callback();
        $this->cacheService->set($key, $result, $ttl);
        return $result;
    }

    protected function forget(string $key): bool
    {
        if ($this->cacheService === null) {
            return false;
        }
        return $this->cacheService->delete($key);
    }
}
""", "AdminUser.php": """<?php

namespace App\\Models;

use App\\Contracts\\AdminInterface;

class AdminUser extends User implements AdminInterface
{
    private array $permissions = [];

    public function __construct(array $data = [])
    {
        parent::__construct($data);
        $this->permissions = $data['permissions'] ?? [];
    }

    public function hasPermission(string $permission): bool
    {
        return in_array($permission, $this->permissions, true);
    }

    public function getPermissions(): array
    {
        return $this->permissions;
    }

    public function isAdmin(): bool
    {
        return true;
    }
}
"""}