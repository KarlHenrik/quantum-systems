import numba
import numpy as np
import scipy.sparse as sps
import scipy.sparse.linalg as spsl

from quantum_systems import QuantumSystem

from quantum_systems.system_helper import (
    add_spin_one_body,
    add_spin_two_body,
    anti_symmetrize_u,
)


@numba.njit(cache=True)
def _trapz(f, x):
    n = len(x)
    delta_x = x[1] - x[0]
    val = 0

    for i in range(1, n):
        val += f[i - 1] + f[i]

    return 0.5 * val * delta_x


@numba.njit(cache=True)
def _shielded_coulomb(x_1, x_2, alpha, a):
    return alpha / np.sqrt((x_1 - x_2) ** 2 + a ** 2)


@numba.njit(cache=True)
def _compute_inner_integral(spf, l, num_grid_points, grid, alpha, a):
    inner_integral = np.zeros((l, l, num_grid_points), dtype=np.complex128)

    for q in range(l):
        for s in range(l):
            for i in range(num_grid_points):
                inner_integral[q, s, i] = _trapz(
                    spf[q]
                    * _shielded_coulomb(grid[i], grid, alpha, a)
                    * spf[s],
                    grid,
                )

    return inner_integral


@numba.njit(cache=True)
def _compute_orbital_integrals(spf, l, inner_integral, grid):
    u = np.zeros((l, l, l, l), dtype=np.complex128)

    for p in range(l):
        for q in range(l):
            for r in range(l):
                for s in range(l):
                    u[p, q, r, s] = _trapz(
                        spf[p] * inner_integral[q, s] * spf[r], grid
                    )

    return u


class OneDimensionalHarmonicOscillator(QuantumSystem):
    def __init__(
        self,
        n,
        l,
        grid_length,
        num_grid_points,
        omega=0.25,
        mass=1,
        a=0.25,
        alpha=1.0,
    ):

        super().__init__(n, l)

        self.omega = omega
        self.mass = mass
        self.a = a
        self.alpha = alpha

        self.grid_length = grid_length
        self.num_grid_points = num_grid_points
        self.grid = np.linspace(
            -self.grid_length, self.grid_length, self.num_grid_points
        )
        self._spf = np.zeros(
            (self.l // 2, self.num_grid_points), dtype=np.complex128
        )

    def setup_system(self):
        dx = self.grid[1] - self.grid[0]

        h_diag = (
            1.0 / (dx ** 2)
            + 0.5 * self.mass * self.omega ** 2 * self.grid[1:-1] ** 2
        )
        h_off_diag = -1.0 / (2 * dx ** 2) * np.ones(self.num_grid_points - 3)

        H = sps.diags([h_diag, h_off_diag, h_off_diag], offsets=[0, -1, 1])

        eigen_energies, eigen_states = spsl.eigs(H, k=self.l // 2, which="SM")
        eigen_energies = eigen_energies
        eigen_states = eigen_states

        self._spf[:, 1:-1] = eigen_states.T / np.sqrt(dx)

        self.__h = np.diag(eigen_energies).astype(np.complex128)
        self._h = add_spin_one_body(self.__h, np=np)

        inner_integral = _compute_inner_integral(
            self._spf,
            self.l // 2,
            self.num_grid_points,
            self.grid,
            self.alpha,
            self.a,
        )

        self.__u = _compute_orbital_integrals(
            self._spf, self.l // 2, inner_integral, self.grid
        )
        self._u = anti_symmetrize_u(add_spin_two_body(self.__u, np=np))

        self.construct_dipole_moment()
        self._f = self.construct_fock_matrix(self._h, self._u)
        self.cast_to_complex()

        if np is not self.np:
            self._h = self.np.asarray(self._h)
            self._u = self.np.asarray(self._u)
            self._f = self.np.asarray(self._f)
            self._spf = self.np.asarray(self._spf)
            self._dipole_moment = self.np.asarray(self._dipole_moment)

    def construct_dipole_moment(self):
        dipole_moment = np.zeros(
            (self.l // 2, self.l // 2), dtype=self._spf.dtype
        )

        for p in range(self.l // 2):
            for q in range(self.l // 2):
                dipole_moment[p, q] = np.trapz(
                    self._spf[p].conj() * self.grid * self._spf[q], self.grid
                )

        self._dipole_moment = np.array(
            [add_spin_one_body(dipole_moment, np=np)]
        )
        self._polarization_vector = np.array([1])
