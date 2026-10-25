from glob import glob

from setuptools import find_packages, setup

package_name = 'physicalai_teleop'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/worlds', glob('worlds/*.world')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='PAI course project',
    maintainer_email='noreply@example.invalid',
    description='UR5e and Robotiq 2F-85 teleoperation in Gazebo Classic',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'teleop_keyboard = physicalai_teleop.teleop_keyboard:main',
        ],
    },
)
