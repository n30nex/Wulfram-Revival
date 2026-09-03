#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "wulfram/physics/physics.hpp"

#include <cmath>
#include <exception>
#include <limits>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace {

using namespace wulfram::physics;

constexpr const char* kWorldCapsuleName = "wulfram.physics.World";
constexpr int kPythonBindingApiVersion = 12;

struct PythonWorld {
    PythonWorld(PhysicsConfig config, TerrainGrid terrain)
        : world(std::move(config), std::move(terrain)) {}

    World world;
};

bool ReadConfigDouble(PyObject* dictionary, const char* key, double& value) {
    PyObject* item = PyDict_GetItemString(dictionary, key);
    if (item == nullptr) {
        return true;
    }
    const double parsed = PyFloat_AsDouble(item);
    if (PyErr_Occurred() != nullptr) {
        PyErr_Format(PyExc_TypeError, "configuration.%s must be a real number", key);
        return false;
    }
    if (!std::isfinite(parsed)) {
        PyErr_Format(PyExc_ValueError, "configuration.%s must be finite", key);
        return false;
    }
    value = parsed;
    return true;
}

bool ReadConfigFloat(PyObject* dictionary, const char* key, float& value) {
    double parsed = value;
    if (!ReadConfigDouble(dictionary, key, parsed)) {
        return false;
    }
    value = static_cast<float>(parsed);
    return true;
}

bool ApplyConfiguration(PyObject* value, PhysicsConfig& config) {
    if (value == nullptr || value == Py_None) {
        return true;
    }
    if (!PyDict_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "configuration must be a dictionary or None");
        return false;
    }

    PyObject* identity = PyDict_GetItemString(value, "configuration_identity");
    if (identity != nullptr) {
        const char* text = PyUnicode_AsUTF8(identity);
        if (text == nullptr) {
            PyErr_SetString(PyExc_TypeError, "configuration.configuration_identity must be a string");
            return false;
        }
        config.configurationIdentity = text;
    }

    TankConfiguration& tank = config.tank;
    return
        ReadConfigDouble(value, "turn_adjust", tank.turnAdjust) &&
        ReadConfigDouble(value, "move_adjust", tank.moveAdjust) &&
        ReadConfigDouble(value, "strafe_adjust", tank.strafeAdjust) &&
        ReadConfigDouble(value, "maximum_velocity", tank.maximumVelocity) &&
        ReadConfigDouble(value, "low_fuel_level", tank.lowFuelLevel) &&
        ReadConfigDouble(value, "maximum_altitude", tank.maximumAltitude) &&
        ReadConfigDouble(value, "gravity_percent", tank.gravityPercent) &&
        ReadConfigDouble(value, "gravity_magnitude", tank.gravityMagnitude) &&
        ReadConfigDouble(value, "minimum_jet_strength", tank.minimumJetStrength) &&
        ReadConfigDouble(value, "jet_response_coefficient", tank.jetResponseCoefficient) &&
        ReadConfigDouble(value, "maximum_fuel", tank.maximumFuel) &&
        ReadConfigDouble(value, "jump_velocity", tank.jumpVelocity) &&
        ReadConfigDouble(value, "jump_acceleration", tank.jumpAcceleration) &&
        ReadConfigDouble(value, "jump_fuel_cost", tank.jumpFuelCost) &&
        ReadConfigDouble(
            value,
            "fuel_regeneration_per_second",
            tank.fuelRegenerationPerSecond) &&
        ReadConfigFloat(value, "density", tank.density) &&
        ReadConfigFloat(value, "baseline_friction", tank.baselineFriction) &&
        ReadConfigFloat(value, "baseline_linear_drag", tank.baselineLinearDrag) &&
        ReadConfigFloat(value, "angular_drag", tank.angularDrag);
}

PythonWorld* GetWorld(PyObject* capsule) {
    return static_cast<PythonWorld*>(PyCapsule_GetPointer(capsule, kWorldCapsuleName));
}

void DestroyWorldCapsule(PyObject* capsule) {
    void* pointer = PyCapsule_GetPointer(capsule, kWorldCapsuleName);
    if (pointer == nullptr) {
        PyErr_Clear();
        return;
    }
    delete static_cast<PythonWorld*>(pointer);
}

bool ReadVec3(PyObject* value, Vec3f& result, const char* argumentName) {
    PyObject* sequence = PySequence_Fast(value, "expected a three-component sequence");
    if (sequence == nullptr) {
        return false;
    }
    if (PySequence_Fast_GET_SIZE(sequence) != 3) {
        Py_DECREF(sequence);
        PyErr_Format(PyExc_ValueError, "%s must contain exactly three numbers", argumentName);
        return false;
    }

    float components[3]{};
    for (Py_ssize_t index = 0; index < 3; ++index) {
        const double component = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(sequence, index));
        if (PyErr_Occurred() != nullptr) {
            Py_DECREF(sequence);
            PyErr_Format(PyExc_TypeError, "%s components must be real numbers", argumentName);
            return false;
        }
        if (!std::isfinite(component)) {
            Py_DECREF(sequence);
            PyErr_Format(PyExc_ValueError, "%s components must be finite", argumentName);
            return false;
        }
        components[index] = static_cast<float>(component);
    }
    Py_DECREF(sequence);
    result = {components[0], components[1], components[2]};
    return true;
}

bool ReadJetShape(PyObject* value, JetShape& result, const char* argumentName) {
    PyObject* points = PySequence_Fast(value, "expected a four-point jet shape");
    if (points == nullptr) {
        return false;
    }
    if (PySequence_Fast_GET_SIZE(points) != 4) {
        Py_DECREF(points);
        PyErr_Format(PyExc_ValueError, "%s must contain exactly four points", argumentName);
        return false;
    }
    for (Py_ssize_t pointIndex = 0; pointIndex < 4; ++pointIndex) {
        PyObject* point = PySequence_Fast(
            PySequence_Fast_GET_ITEM(points, pointIndex),
            "expected a seven-component jet point");
        if (point == nullptr) {
            Py_DECREF(points);
            return false;
        }
        if (PySequence_Fast_GET_SIZE(point) != 7) {
            Py_DECREF(point);
            Py_DECREF(points);
            PyErr_Format(
                PyExc_ValueError,
                "%s point %zd must contain position, direction, and flag",
                argumentName,
                pointIndex);
            return false;
        }
        float components[6]{};
        for (Py_ssize_t componentIndex = 0; componentIndex < 6; ++componentIndex) {
            const double component = PyFloat_AsDouble(
                PySequence_Fast_GET_ITEM(point, componentIndex));
            if (PyErr_Occurred() != nullptr || !std::isfinite(component)) {
                Py_DECREF(point);
                Py_DECREF(points);
                PyErr_Format(
                    PyExc_ValueError,
                    "%s point %zd components must be finite numbers",
                    argumentName,
                    pointIndex);
                return false;
            }
            components[componentIndex] = static_cast<float>(component);
        }
        const int legacyFlag = PyObject_IsTrue(PySequence_Fast_GET_ITEM(point, 6));
        if (legacyFlag < 0) {
            Py_DECREF(point);
            Py_DECREF(points);
            return false;
        }
        result.points[static_cast<std::size_t>(pointIndex)] = {
            {components[0], components[1], components[2]},
            {components[3], components[4], components[5]},
            legacyFlag != 0,
        };
        Py_DECREF(point);
    }
    Py_DECREF(points);
    return true;
}

bool ReadMatrix3(PyObject* value, Matrix3d& result, const char* argumentName) {
    PyObject* sequence = PySequence_Fast(value, "expected a nine-component sequence");
    if (sequence == nullptr) {
        return false;
    }
    if (PySequence_Fast_GET_SIZE(sequence) != 9) {
        Py_DECREF(sequence);
        PyErr_Format(PyExc_ValueError, "%s must contain exactly nine numbers", argumentName);
        return false;
    }
    for (Py_ssize_t index = 0; index < 9; ++index) {
        const double component = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(sequence, index));
        if (PyErr_Occurred() != nullptr) {
            Py_DECREF(sequence);
            PyErr_Format(PyExc_TypeError, "%s components must be real numbers", argumentName);
            return false;
        }
        if (!std::isfinite(component)) {
            Py_DECREF(sequence);
            PyErr_Format(PyExc_ValueError, "%s components must be finite", argumentName);
            return false;
        }
        result.elements[index] = component;
    }
    Py_DECREF(sequence);
    return true;
}

bool ReadVehicleInput(PyObject* value, VehicleInput& result, const char* argumentName) {
    PyObject* sequence = PySequence_Fast(value, "expected a six- or seven-component sequence");
    if (sequence == nullptr) {
        return false;
    }
    const Py_ssize_t count = PySequence_Fast_GET_SIZE(sequence);
    if (count != 6 && count != 7) {
        Py_DECREF(sequence);
        PyErr_Format(
            PyExc_ValueError,
            "%s must contain six legacy controls or those controls followed by jump",
            argumentName);
        return false;
    }
    float components[7]{};
    for (Py_ssize_t index = 0; index < count; ++index) {
        const double component = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(sequence, index));
        if (PyErr_Occurred() != nullptr || !std::isfinite(component)) {
            Py_DECREF(sequence);
            PyErr_Format(PyExc_ValueError, "%s components must be finite numbers", argumentName);
            return false;
        }
        components[index] = static_cast<float>(component);
    }
    Py_DECREF(sequence);
    result = {
        components[0], components[1], components[2], components[3],
        components[4], components[5], components[6],
    };
    return true;
}

bool ApplyPhysicalProperties(PyObject* value, PhysicalProperties& properties) {
    if (value == nullptr || value == Py_None) {
        return true;
    }
    if (!PyDict_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "active_properties must be a dictionary or None");
        return false;
    }
    PyObject* inertia = PyDict_GetItemString(value, "inertia");
    return ReadConfigFloat(value, "mass", properties.mass) &&
        (inertia == nullptr || ReadVec3(inertia, properties.inertia, "active_properties.inertia")) &&
        ReadConfigFloat(value, "friction", properties.friction) &&
        ReadConfigFloat(value, "linear_drag", properties.linearDrag) &&
        ReadConfigFloat(value, "angular_drag", properties.angularDrag);
}

bool ReadFloatSequence(
    PyObject* value,
    std::size_t expectedCount,
    std::vector<float>& result,
    const char* argumentName) {
    PyObject* sequence = PySequence_Fast(value, "expected a sequence of terrain heights");
    if (sequence == nullptr) {
        return false;
    }
    const Py_ssize_t count = PySequence_Fast_GET_SIZE(sequence);
    if (count < 0 || static_cast<std::size_t>(count) != expectedCount) {
        Py_DECREF(sequence);
        PyErr_Format(
            PyExc_ValueError,
            "%s must contain exactly %zu heights (received %zd)",
            argumentName,
            expectedCount,
            count);
        return false;
    }

    result.reserve(expectedCount);
    for (Py_ssize_t index = 0; index < count; ++index) {
        const double component = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(sequence, index));
        if (PyErr_Occurred() != nullptr) {
            Py_DECREF(sequence);
            PyErr_Format(PyExc_TypeError, "%s values must be real numbers", argumentName);
            return false;
        }
        if (!std::isfinite(component)) {
            Py_DECREF(sequence);
            PyErr_Format(PyExc_ValueError, "%s values must be finite", argumentName);
            return false;
        }
        result.push_back(static_cast<float>(component));
    }
    Py_DECREF(sequence);
    return true;
}

PyObject* Vec3ToTuple(const Vec3f& value) {
    return Py_BuildValue("(fff)", value.x, value.y, value.z);
}

PyObject* MatrixToTuple(const Matrix3d& value) {
    PyObject* tuple = PyTuple_New(9);
    if (tuple == nullptr) {
        return nullptr;
    }
    for (Py_ssize_t index = 0; index < 9; ++index) {
        PyObject* component = PyFloat_FromDouble(value.elements[index]);
        if (component == nullptr) {
            Py_DECREF(tuple);
            return nullptr;
        }
        PyTuple_SET_ITEM(tuple, index, component);
    }
    return tuple;
}

PyObject* VehicleInputToTuple(const VehicleInput& value) {
    return Py_BuildValue("(ffffff)", value.turn, value.move, value.strafe, value.jet, value.tilt, value.roll);
}

bool SetDictValue(PyObject* dictionary, const char* key, PyObject* value);

PyObject* PhysicalPropertiesToDictionary(const PhysicalProperties& value) {
    PyObject* result = PyDict_New();
    if (result == nullptr) {
        return nullptr;
    }
    if (!SetDictValue(result, "mass", PyFloat_FromDouble(value.mass)) ||
        !SetDictValue(result, "inertia", Vec3ToTuple(value.inertia)) ||
        !SetDictValue(result, "friction", PyFloat_FromDouble(value.friction)) ||
        !SetDictValue(result, "linear_drag", PyFloat_FromDouble(value.linearDrag)) ||
        !SetDictValue(result, "angular_drag", PyFloat_FromDouble(value.angularDrag))) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

bool SetDictValue(PyObject* dictionary, const char* key, PyObject* value) {
    if (value == nullptr) {
        return false;
    }
    const int result = PyDict_SetItemString(dictionary, key, value);
    Py_DECREF(value);
    return result == 0;
}

PyObject* BodyToDictionary(const SnapshotEntity& entity) {
    PyObject* result = PyDict_New();
    if (result == nullptr) {
        return nullptr;
    }
    const BodyState& body = entity.body;
    if (!SetDictValue(result, "id", PyLong_FromUnsignedLongLong(entity.id)) ||
        !SetDictValue(
            result,
            "last_processed_input",
            PyLong_FromUnsignedLongLong(entity.lastProcessedInput)) ||
        !SetDictValue(result, "position", Vec3ToTuple(body.position)) ||
        !SetDictValue(result, "linear_velocity", Vec3ToTuple(body.linearVelocity)) ||
        !SetDictValue(result, "linear_acceleration", Vec3ToTuple(body.linearAcceleration)) ||
        !SetDictValue(result, "euler_radians", Vec3ToTuple(body.eulerRadians)) ||
        !SetDictValue(result, "angular_velocity", Vec3ToTuple(body.angularVelocity)) ||
        !SetDictValue(result, "angular_acceleration", Vec3ToTuple(body.angularAcceleration)) ||
        !SetDictValue(result, "orientation", MatrixToTuple(body.orientation)) ||
        !SetDictValue(result, "mass", PyFloat_FromDouble(body.mass)) ||
        !SetDictValue(result, "inertia", Vec3ToTuple(body.inertia)) ||
        !SetDictValue(result, "active_friction", PyFloat_FromDouble(body.activeFriction)) ||
        !SetDictValue(result, "active_linear_drag", PyFloat_FromDouble(body.activeLinearDrag)) ||
        !SetDictValue(result, "angular_drag", PyFloat_FromDouble(body.angularDrag)) ||
        !SetDictValue(result, "legacy_type_code", PyLong_FromUnsignedLong(body.legacyTypeCode)) ||
        !SetDictValue(
            result,
            "pre_gravity_acceleration_is_significant",
            PyBool_FromLong(body.preGravityAccelerationIsSignificant ? 1 : 0)) ||
        !SetDictValue(result, "damping_enabled", PyBool_FromLong(body.dampingEnabled ? 1 : 0)) ||
        !SetDictValue(
            result,
            "velocity_only_motion",
            PyBool_FromLong(body.velocityOnlyMotion ? 1 : 0)) ||
        !SetDictValue(
            result,
            "settling_contact_threshold",
            PyFloat_FromDouble(body.settlingContactThreshold)) ||
        !SetDictValue(
            result,
            "baseline_physical_properties",
            PhysicalPropertiesToDictionary(entity.baselinePhysicalProperties)) ||
        !SetDictValue(result, "fuel", PyFloat_FromDouble(entity.fuel)) ||
        !SetDictValue(result, "jet_strength", PyFloat_FromDouble(entity.jetStrength)) ||
        !SetDictValue(result, "current_input", VehicleInputToTuple(entity.currentInput)) ||
        !SetDictValue(result, "jump_input", PyFloat_FromDouble(entity.currentInput.jump)) ||
        !SetDictValue(
            result,
            "is_static",
            PyBool_FromLong(entity.motionType == BodyMotionType::Static ? 1 : 0)) ||
        !SetDictValue(
            result,
            "controller_type",
            PyLong_FromUnsignedLong(static_cast<unsigned long>(entity.controllerType))) ||
        !SetDictValue(result, "alive", PyBool_FromLong(entity.alive ? 1 : 0))) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

PyObject* TraceToDictionary(const TraceEvent& event) {
    PyObject* result = PyDict_New();
    if (result == nullptr) {
        return nullptr;
    }
    if (!SetDictValue(result, "type", PyLong_FromUnsignedLong(static_cast<unsigned long>(event.type))) ||
        !SetDictValue(result, "tick", PyLong_FromUnsignedLongLong(event.tick)) ||
        !SetDictValue(result, "entity_id", PyLong_FromUnsignedLongLong(event.entity)) ||
        !SetDictValue(result, "step_milliseconds", PyLong_FromUnsignedLong(event.stepMilliseconds)) ||
        !SetDictValue(result, "feature", PyLong_FromLong(event.feature)) ||
        !SetDictValue(result, "point", Vec3ToTuple(event.point)) ||
        !SetDictValue(result, "normal", Vec3ToTuple(event.normal)) ||
        !SetDictValue(result, "value", Vec3ToTuple(event.value)) ||
        !SetDictValue(result, "scalar0", PyFloat_FromDouble(event.scalar0)) ||
        !SetDictValue(result, "scalar1", PyFloat_FromDouble(event.scalar1)) ||
        !SetDictValue(result, "secondary_feature", PyLong_FromLong(event.secondaryFeature)) ||
        !SetDictValue(result, "bucket", PyLong_FromLong(event.bucket)) ||
        !SetDictValue(
            result,
            "other_entity_id",
            PyLong_FromUnsignedLongLong(event.otherEntity))) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

void SetCppException() {
    try {
        throw;
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what());
    } catch (...) {
        PyErr_SetString(PyExc_RuntimeError, "portable physics operation failed");
    }
}

PyObject* CreateWorld(PyObject*, PyObject* args, PyObject* kwargs) {
    unsigned long long countXValue = 0;
    unsigned long long countYValue = 0;
    double spacingX = 0.0;
    double spacingY = 0.0;
    PyObject* heightsObject = nullptr;
    const char* terrainIdentity = nullptr;
    PyObject* configurationObject = Py_None;
    static const char* keywords[] = {
        "count_x",
        "count_y",
        "spacing_x",
        "spacing_y",
        "heights_x_major",
        "terrain_identity",
        "configuration",
        nullptr,
    };
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "KKddOs|O:create_world",
            const_cast<char**>(keywords),
            &countXValue,
            &countYValue,
            &spacingX,
            &spacingY,
            &heightsObject,
            &terrainIdentity,
            &configurationObject)) {
        return nullptr;
    }
    if (countXValue < 2 || countYValue < 2 || !std::isfinite(spacingX) ||
        !std::isfinite(spacingY) || spacingX <= 0.0 || spacingY <= 0.0 ||
        countXValue > std::numeric_limits<std::size_t>::max() ||
        countYValue > std::numeric_limits<std::size_t>::max()) {
        PyErr_SetString(PyExc_ValueError, "terrain dimensions and spacing must define a valid grid");
        return nullptr;
    }
    const auto countX = static_cast<std::size_t>(countXValue);
    const auto countY = static_cast<std::size_t>(countYValue);
    if (countY != 0 && countX > std::numeric_limits<std::size_t>::max() / countY) {
        PyErr_SetString(PyExc_OverflowError, "terrain dimensions overflow addressable memory");
        return nullptr;
    }

    try {
        PhysicsConfig config = DefaultPhysicsConfig();
        if (!ApplyConfiguration(configurationObject, config)) {
            return nullptr;
        }
        std::vector<float> heights{};
        if (!ReadFloatSequence(heightsObject, countX * countY, heights, "heights_x_major")) {
            return nullptr;
        }
        auto world = std::make_unique<PythonWorld>(
            std::move(config),
            TerrainGrid(
                countX,
                countY,
                static_cast<float>(spacingX),
                static_cast<float>(spacingY),
                std::move(heights),
                terrainIdentity));
        PyObject* capsule = PyCapsule_New(world.get(), kWorldCapsuleName, DestroyWorldCapsule);
        if (capsule == nullptr) {
            return nullptr;
        }
        world.release();
        return capsule;
    } catch (...) {
        SetCppException();
        return nullptr;
    }
}

PyObject* CreateVehicle(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* capsule = nullptr;
    unsigned long long entityId = 0;
    unsigned int team = 0;
    PyObject* positionObject = nullptr;
    PyObject* velocityObject = nullptr;
    PyObject* eulerObject = nullptr;
    PyObject* angularVelocityObject = nullptr;
    PyObject* collisionBytesObject = nullptr;
    const char* collisionIdentity = nullptr;
    double fuel = 33000.0;
    PyObject* orientationObject = Py_None;
    PyObject* linearAccelerationObject = Py_None;
    PyObject* angularAccelerationObject = Py_None;
    PyObject* baselinePropertiesObject = Py_None;
    PyObject* activePropertiesObject = Py_None;
    PyObject* currentInputObject = Py_None;
    unsigned long long lastProcessedInput = 0;
    double jetStrength = 0.0;
    unsigned int legacyTypeCode = 0;
    int preGravityAccelerationIsSignificant = 0;
    int dampingEnabled = 1;
    int velocityOnlyMotion = 0;
    double settlingContactThreshold = 0.0;
    PyObject* jetShapeObject = Py_None;
    unsigned int vehicleType = 0;
    static const char* keywords[] = {
        "world",
        "entity_id",
        "team",
        "position",
        "linear_velocity",
        "euler_radians",
        "angular_velocity",
        "collision_asset",
        "collision_identity",
        "fuel",
        "orientation",
        "linear_acceleration",
        "angular_acceleration",
        "baseline_properties",
        "active_properties",
        "current_input",
        "last_processed_input",
        "jet_strength",
        "legacy_type_code",
        "pre_gravity_acceleration_is_significant",
        "damping_enabled",
        "velocity_only_motion",
        "settling_contact_threshold",
        "jet_shape",
        "vehicle_type",
        nullptr,
    };
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "OKIOOOOOs|dOOOOOOKdIpppdOI:create_vehicle",
            const_cast<char**>(keywords),
            &capsule,
            &entityId,
            &team,
            &positionObject,
            &velocityObject,
            &eulerObject,
            &angularVelocityObject,
            &collisionBytesObject,
            &collisionIdentity,
            &fuel,
            &orientationObject,
            &linearAccelerationObject,
            &angularAccelerationObject,
            &baselinePropertiesObject,
            &activePropertiesObject,
            &currentInputObject,
            &lastProcessedInput,
            &jetStrength,
            &legacyTypeCode,
            &preGravityAccelerationIsSignificant,
            &dampingEnabled,
            &velocityOnlyMotion,
            &settlingContactThreshold,
            &jetShapeObject,
            &vehicleType)) {
        return nullptr;
    }
    PythonWorld* pythonWorld = GetWorld(capsule);
    if (pythonWorld == nullptr) {
        return nullptr;
    }
    if (entityId == 0 || vehicleType > 1 || !std::isfinite(fuel) || fuel < 0.0 ||
        !std::isfinite(jetStrength) ||
        !std::isfinite(settlingContactThreshold)) {
        PyErr_SetString(
            PyExc_ValueError,
            "entity_id must be nonzero, vehicle_type must be 0 or 1, and replay scalars must be finite");
        return nullptr;
    }

    Vec3f position{};
    Vec3f velocity{};
    Vec3f euler{};
    Vec3f angularVelocity{};
    Vec3f linearAcceleration{};
    Vec3f angularAcceleration{};
    if (!ReadVec3(positionObject, position, "position") ||
        !ReadVec3(velocityObject, velocity, "linear_velocity") ||
        !ReadVec3(eulerObject, euler, "euler_radians") ||
        !ReadVec3(angularVelocityObject, angularVelocity, "angular_velocity")) {
        return nullptr;
    }
    if (linearAccelerationObject != Py_None &&
        !ReadVec3(linearAccelerationObject, linearAcceleration, "linear_acceleration")) {
        return nullptr;
    }
    if (angularAccelerationObject != Py_None &&
        !ReadVec3(angularAccelerationObject, angularAcceleration, "angular_acceleration")) {
        return nullptr;
    }
    Matrix3d orientation = Matrix3d::FromEulerAngles(euler);
    if (orientationObject != Py_None &&
        !ReadMatrix3(orientationObject, orientation, "orientation")) {
        return nullptr;
    }
    VehicleInput currentInput{};
    if (currentInputObject != Py_None &&
        !ReadVehicleInput(currentInputObject, currentInput, "current_input")) {
        return nullptr;
    }
    const bool scout = vehicleType == 1;
    JetShape jetShape = scout
        ? (team == 2 ? MedicBlueJetShape() : MedicRedJetShape())
        : (team == 2 ? TankBlueJetShape() : TankRedJetShape());
    if (jetShapeObject != Py_None &&
        !ReadJetShape(jetShapeObject, jetShape, "jet_shape")) {
        return nullptr;
    }

    Py_buffer collisionBytes{};
    if (PyObject_GetBuffer(collisionBytesObject, &collisionBytes, PyBUF_SIMPLE) != 0) {
        PyErr_SetString(PyExc_TypeError, "collision_asset must expose a contiguous byte buffer");
        return nullptr;
    }
    bool collisionBytesReleased = false;
    try {
        CollisionShape collisionShape{};
        const bool decoded = DecodeLegacyCollisionShape(
            static_cast<const std::uint8_t*>(collisionBytes.buf),
            static_cast<std::size_t>(collisionBytes.len),
            collisionShape,
            collisionIdentity);
        PyBuffer_Release(&collisionBytes);
        collisionBytesReleased = true;
        if (!decoded) {
            PyErr_SetString(PyExc_ValueError, "collision_asset is not a valid legacy collision shape");
            return nullptr;
        }

        const TankConfiguration& vehicle = scout
            ? pythonWorld->world.Config().scout
            : pythonWorld->world.Config().tank;
        EntityDefinition definition{};
        definition.id = entityId;
        definition.initialState.position = position;
        definition.initialState.linearVelocity = velocity;
        definition.initialState.eulerRadians = euler;
        definition.initialState.angularVelocity = angularVelocity;
        definition.initialState.linearAcceleration = linearAcceleration;
        definition.initialState.angularAcceleration = angularAcceleration;
        definition.initialState.orientation = orientation;
        definition.initialState.legacyTypeCode = legacyTypeCode;
        definition.initialState.preGravityAccelerationIsSignificant =
            preGravityAccelerationIsSignificant != 0;
        definition.initialState.dampingEnabled = dampingEnabled != 0;
        definition.initialState.velocityOnlyMotion = velocityOnlyMotion != 0;
        definition.initialState.settlingContactThreshold = settlingContactThreshold;
        definition.collisionShape = std::move(collisionShape);
        definition.jetShape = jetShape;
        definition.controllerType = scout ? ControllerType::Scout : ControllerType::Tank;
        definition.fuel = static_cast<float>(fuel);
        definition.jetStrength = static_cast<float>(jetStrength);
        definition.initialInput = currentInput;
        definition.lastProcessedInput = lastProcessedInput;
        definition.alive = true;
        definition.baselinePhysicalProperties = DeriveTankPhysicalProperties(
            definition.collisionShape,
            vehicle.density,
            vehicle.baselineFriction,
            vehicle.baselineLinearDrag,
            vehicle.angularDrag);
        if (baselinePropertiesObject != Py_None &&
            !ApplyPhysicalProperties(
                baselinePropertiesObject,
                definition.baselinePhysicalProperties)) {
            return nullptr;
        }
        if (activePropertiesObject != Py_None) {
            PhysicalProperties active = definition.baselinePhysicalProperties;
            if (!ApplyPhysicalProperties(activePropertiesObject, active)) {
                return nullptr;
            }
            definition.activePhysicalProperties = active;
        }
        if (!pythonWorld->world.CreateEntity(definition)) {
            PyErr_Format(PyExc_ValueError, "could not create vehicle entity %llu", entityId);
            return nullptr;
        }
        Py_RETURN_NONE;
    } catch (...) {
        if (!collisionBytesReleased) {
            PyBuffer_Release(&collisionBytes);
        }
        SetCppException();
        return nullptr;
    }
}

PyObject* CreateStaticCollider(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* capsule = nullptr;
    unsigned long long entityId = 0;
    PyObject* positionObject = nullptr;
    PyObject* eulerObject = nullptr;
    PyObject* collisionBytesObject = nullptr;
    const char* collisionIdentity = nullptr;
    double friction = 1.0;
    PyObject* orientationObject = Py_None;
    static const char* keywords[] = {
        "world",
        "entity_id",
        "position",
        "euler_radians",
        "collision_asset",
        "collision_identity",
        "friction",
        "orientation",
        nullptr,
    };
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "OKOOOs|dO:create_static_collider",
            const_cast<char**>(keywords),
            &capsule,
            &entityId,
            &positionObject,
            &eulerObject,
            &collisionBytesObject,
            &collisionIdentity,
            &friction,
            &orientationObject)) {
        return nullptr;
    }
    PythonWorld* pythonWorld = GetWorld(capsule);
    if (pythonWorld == nullptr) {
        return nullptr;
    }
    if (entityId == 0 || !std::isfinite(friction) || friction < 0.0) {
        PyErr_SetString(
            PyExc_ValueError,
            "entity_id must be nonzero and static-collider friction must be finite and nonnegative");
        return nullptr;
    }

    Vec3f position{};
    Vec3f euler{};
    if (!ReadVec3(positionObject, position, "position") ||
        !ReadVec3(eulerObject, euler, "euler_radians")) {
        return nullptr;
    }
    Matrix3d orientation = Matrix3d::FromEulerAngles(euler);
    if (orientationObject != Py_None &&
        !ReadMatrix3(orientationObject, orientation, "orientation")) {
        return nullptr;
    }

    Py_buffer collisionBytes{};
    if (PyObject_GetBuffer(collisionBytesObject, &collisionBytes, PyBUF_SIMPLE) != 0) {
        PyErr_SetString(PyExc_TypeError, "collision_asset must expose a contiguous byte buffer");
        return nullptr;
    }
    bool collisionBytesReleased = false;
    try {
        CollisionShape shape{};
        const bool decoded = DecodeLegacyCollisionShape(
            static_cast<const std::uint8_t*>(collisionBytes.buf),
            static_cast<std::size_t>(collisionBytes.len),
            shape,
            collisionIdentity);
        PyBuffer_Release(&collisionBytes);
        collisionBytesReleased = true;
        if (!decoded) {
            PyErr_SetString(PyExc_ValueError, "collision_asset is not a valid legacy collision shape");
            return nullptr;
        }

        EntityDefinition definition{};
        definition.id = entityId;
        definition.initialState.position = position;
        definition.initialState.eulerRadians = euler;
        definition.initialState.orientation = orientation;
        definition.collisionShape = std::move(shape);
        definition.motionType = BodyMotionType::Static;
        definition.controllerType = ControllerType::None;
        definition.baselinePhysicalProperties.mass = 1.0F;
        definition.baselinePhysicalProperties.inertia = {1.0F, 1.0F, 1.0F};
        definition.baselinePhysicalProperties.friction = static_cast<float>(friction);
        definition.baselinePhysicalProperties.linearDrag = 0.0F;
        definition.baselinePhysicalProperties.angularDrag = 0.0F;
        definition.alive = true;
        if (!pythonWorld->world.CreateEntity(definition)) {
            PyErr_Format(PyExc_ValueError, "could not create static collider %llu", entityId);
            return nullptr;
        }
        Py_RETURN_NONE;
    } catch (...) {
        if (!collisionBytesReleased) {
            PyBuffer_Release(&collisionBytes);
        }
        SetCppException();
        return nullptr;
    }
}

PyObject* CreateProjectile(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* capsule = nullptr;
    unsigned long long entityId = 0;
    PyObject* positionObject = nullptr;
    PyObject* velocityObject = nullptr;
    PyObject* eulerObject = nullptr;
    PyObject* collisionBytesObject = nullptr;
    const char* collisionIdentity = nullptr;
    double density = 10000.0;
    double friction = 0.1;
    double linearDrag = 0.00001;
    double angularDrag = 0.0;
    static const char* keywords[] = {
        "world", "entity_id", "position", "linear_velocity", "euler_radians",
        "collision_asset", "collision_identity", "density", "friction",
        "linear_drag", "angular_drag", nullptr,
    };
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "OKOOOOs|dddd:create_projectile",
            const_cast<char**>(keywords),
            &capsule,
            &entityId,
            &positionObject,
            &velocityObject,
            &eulerObject,
            &collisionBytesObject,
            &collisionIdentity,
            &density,
            &friction,
            &linearDrag,
            &angularDrag)) {
        return nullptr;
    }
    PythonWorld* pythonWorld = GetWorld(capsule);
    if (pythonWorld == nullptr) return nullptr;
    if (entityId == 0 || !std::isfinite(density) || density <= 0.0 ||
        !std::isfinite(friction) || friction < 0.0 ||
        !std::isfinite(linearDrag) || linearDrag < 0.0 ||
        !std::isfinite(angularDrag) || angularDrag < 0.0) {
        PyErr_SetString(PyExc_ValueError, "projectile physical properties must be finite and valid");
        return nullptr;
    }
    Vec3f position{};
    Vec3f velocity{};
    Vec3f euler{};
    if (!ReadVec3(positionObject, position, "position") ||
        !ReadVec3(velocityObject, velocity, "linear_velocity") ||
        !ReadVec3(eulerObject, euler, "euler_radians")) {
        return nullptr;
    }
    Py_buffer collisionBytes{};
    if (PyObject_GetBuffer(collisionBytesObject, &collisionBytes, PyBUF_SIMPLE) != 0) {
        PyErr_SetString(PyExc_TypeError, "collision_asset must expose a contiguous byte buffer");
        return nullptr;
    }
    bool collisionBytesReleased = false;
    try {
        CollisionShape shape{};
        const bool decoded = DecodeLegacyCollisionShape(
            static_cast<const std::uint8_t*>(collisionBytes.buf),
            static_cast<std::size_t>(collisionBytes.len),
            shape,
            collisionIdentity);
        PyBuffer_Release(&collisionBytes);
        collisionBytesReleased = true;
        if (!decoded) {
            PyErr_SetString(PyExc_ValueError, "collision_asset is not a valid legacy collision shape");
            return nullptr;
        }
        EntityDefinition definition{};
        definition.id = entityId;
        definition.initialState.position = position;
        definition.initialState.linearVelocity = velocity;
        definition.initialState.eulerRadians = euler;
        definition.initialState.orientation = Matrix3d::FromEulerAngles(euler);
        definition.collisionShape = std::move(shape);
        definition.motionType = BodyMotionType::Dynamic;
        definition.controllerType = ControllerType::None;
        definition.baselinePhysicalProperties = DeriveTankPhysicalProperties(
            definition.collisionShape,
            static_cast<float>(density),
            static_cast<float>(friction),
            static_cast<float>(linearDrag),
            static_cast<float>(angularDrag));
        definition.alive = true;
        if (!pythonWorld->world.CreateEntity(definition)) {
            PyErr_Format(PyExc_ValueError, "could not create projectile entity %llu", entityId);
            return nullptr;
        }
        Py_RETURN_NONE;
    } catch (...) {
        if (!collisionBytesReleased) PyBuffer_Release(&collisionBytes);
        SetCppException();
        return nullptr;
    }
}

PyObject* DestroyEntity(PyObject*, PyObject* args) {
    PyObject* capsule = nullptr;
    unsigned long long entityId = 0;
    if (!PyArg_ParseTuple(args, "OK:destroy_entity", &capsule, &entityId)) {
        return nullptr;
    }
    PythonWorld* world = GetWorld(capsule);
    if (world == nullptr) {
        return nullptr;
    }
    if (!world->world.DestroyEntity(entityId)) {
        PyErr_Format(PyExc_KeyError, "physics entity %llu does not exist", entityId);
        return nullptr;
    }
    Py_RETURN_NONE;
}

PyObject* SubmitInput(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* capsule = nullptr;
    unsigned long long entityId = 0;
    unsigned long long sequence = 0;
    unsigned long long targetTick = 0;
    unsigned long long timeMilliseconds = 0;
    double turn = 0.0;
    double move = 0.0;
    double strafe = 0.0;
    double jet = 0.0;
    double tilt = 0.0;
    double roll = 0.0;
    double jump = 0.0;
    static const char* keywords[] = {
        "world",
        "entity_id",
        "sequence",
        "target_tick",
        "time_milliseconds",
        "turn",
        "move",
        "strafe",
        "jet",
        "tilt",
        "roll",
        "jump",
        nullptr,
    };
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "OKKKKdddddd|d:submit_input",
            const_cast<char**>(keywords),
            &capsule,
            &entityId,
            &sequence,
            &targetTick,
            &timeMilliseconds,
            &turn,
            &move,
            &strafe,
            &jet,
            &tilt,
            &roll,
            &jump)) {
        return nullptr;
    }
    PythonWorld* world = GetWorld(capsule);
    if (world == nullptr) {
        return nullptr;
    }
    if (!std::isfinite(turn) || !std::isfinite(move) || !std::isfinite(strafe) ||
        !std::isfinite(jet) || !std::isfinite(tilt) || !std::isfinite(roll) ||
        !std::isfinite(jump)) {
        PyErr_SetString(PyExc_ValueError, "vehicle input components must be finite");
        return nullptr;
    }
    InputEvent event{};
    event.sequence = sequence;
    event.targetTick = targetTick;
    event.timeMilliseconds = timeMilliseconds;
    event.controls = {
        static_cast<float>(turn),
        static_cast<float>(move),
        static_cast<float>(strafe),
        static_cast<float>(jet),
        static_cast<float>(tilt),
        static_cast<float>(roll),
        static_cast<float>(jump),
    };
    try {
        if (!world->world.SubmitInput(entityId, event)) {
            PyErr_Format(
                PyExc_ValueError,
                "input sequence %llu was rejected for physics entity %llu",
                sequence,
                entityId);
            return nullptr;
        }
        Py_RETURN_NONE;
    } catch (...) {
        SetCppException();
        return nullptr;
    }
}

PyObject* ApplyAuthoritativeMutation(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* capsule = nullptr;
    unsigned long long entityId = 0;
    PyObject* positionObject = Py_None;
    PyObject* orientationObject = Py_None;
    static const char* keywords[] = {
        "world", "entity_id", "position", "orientation", nullptr,
    };
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "OKO|O:apply_authoritative_mutation",
            const_cast<char**>(keywords),
            &capsule,
            &entityId,
            &positionObject,
            &orientationObject)) {
        return nullptr;
    }
    PythonWorld* world = GetWorld(capsule);
    if (world == nullptr) return nullptr;
    AuthoritativeMutation mutation{};
    Vec3f position{};
    if (!ReadVec3(positionObject, position, "position")) return nullptr;
    mutation.position = position;
    Matrix3d orientation{};
    if (orientationObject != Py_None) {
        if (!ReadMatrix3(orientationObject, orientation, "orientation")) return nullptr;
        mutation.orientation = orientation;
    }
    try {
        if (world->world.GetBodyState(entityId) == nullptr) {
            PyErr_Format(PyExc_KeyError, "physics entity %llu does not exist", entityId);
            return nullptr;
        }
        return PyBool_FromLong(world->world.ApplyAuthoritativeMutation(entityId, mutation) ? 1 : 0);
    } catch (...) {
        SetCppException();
        return nullptr;
    }
}

PyObject* StepWorld(PyObject*, PyObject* args) {
    PyObject* capsule = nullptr;
    unsigned long long tick = 0;
    unsigned int stepMilliseconds = 0;
    if (!PyArg_ParseTuple(args, "OKI:step_world", &capsule, &tick, &stepMilliseconds)) {
        return nullptr;
    }
    PythonWorld* world = GetWorld(capsule);
    if (world == nullptr) {
        return nullptr;
    }

    bool succeeded = false;
    std::exception_ptr error{};
    PyThreadState* threadState = PyEval_SaveThread();
    try {
        succeeded = world->world.StepWorld(tick, stepMilliseconds);
    } catch (...) {
        error = std::current_exception();
    }
    PyEval_RestoreThread(threadState);

    if (error != nullptr) {
        try {
            std::rethrow_exception(error);
        } catch (...) {
            SetCppException();
        }
        return nullptr;
    }
    if (!succeeded) {
        PyErr_Format(PyExc_ValueError, "authoritative tick %llu is older than the current world tick", tick);
        return nullptr;
    }
    Py_RETURN_NONE;
}

PyObject* ResolveInitialSpawnPose(PyObject*, PyObject* args) {
    PyObject* capsule = nullptr;
    unsigned long long entityId = 0;
    if (!PyArg_ParseTuple(
            args, "OK:resolve_initial_spawn_pose", &capsule, &entityId)) {
        return nullptr;
    }
    PythonWorld* world = GetWorld(capsule);
    if (world == nullptr) {
        return nullptr;
    }
    const std::optional<float> lift = world->world.ResolveInitialSpawnPose(entityId);
    if (!lift.has_value()) {
        PyErr_Format(
            PyExc_ValueError,
            "could not resolve initial spawn pose for entity %llu",
            entityId);
        return nullptr;
    }
    return PyFloat_FromDouble(*lift);
}

PyObject* TraceSegment(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* capsule = nullptr;
    PyObject* startObject = nullptr;
    PyObject* endObject = nullptr;
    unsigned long long ignoredEntity = 0;
    unsigned long long secondIgnoredEntity = 0;
    static const char* keywords[] = {
        "world", "start", "end", "ignored_entity", "second_ignored_entity", nullptr,
    };
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "OOO|KK:trace_segment",
            const_cast<char**>(keywords),
            &capsule,
            &startObject,
            &endObject,
            &ignoredEntity,
            &secondIgnoredEntity)) {
        return nullptr;
    }
    PythonWorld* world = GetWorld(capsule);
    if (world == nullptr) return nullptr;
    Vec3f start{};
    Vec3f end{};
    if (!ReadVec3(startObject, start, "start") || !ReadVec3(endObject, end, "end")) {
        return nullptr;
    }
    try {
        const SegmentHit hit = world->world.TraceSegment(
            start, end, ignoredEntity, secondIgnoredEntity);
        PyObject* result = PyDict_New();
        if (result == nullptr ||
            !SetDictValue(result, "hit", PyBool_FromLong(hit.hit ? 1 : 0)) ||
            !SetDictValue(result, "entity_id", PyLong_FromUnsignedLongLong(hit.entity)) ||
            !SetDictValue(result, "point", Vec3ToTuple(hit.point)) ||
            !SetDictValue(result, "normal", Vec3ToTuple(hit.normal)) ||
            !SetDictValue(result, "fraction", PyFloat_FromDouble(hit.fraction))) {
            Py_XDECREF(result);
            return nullptr;
        }
        return result;
    } catch (...) {
        SetCppException();
        return nullptr;
    }
}

PyObject* ApplyLinearImpulse(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* capsule = nullptr;
    unsigned long long entityId = 0;
    PyObject* impulseObject = nullptr;
    static const char* keywords[] = {"world", "entity_id", "impulse", nullptr};
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "OKO:apply_linear_impulse",
            const_cast<char**>(keywords),
            &capsule,
            &entityId,
            &impulseObject)) {
        return nullptr;
    }
    PythonWorld* world = GetWorld(capsule);
    if (world == nullptr) return nullptr;
    Vec3f impulse{};
    if (!ReadVec3(impulseObject, impulse, "impulse")) return nullptr;
    return PyBool_FromLong(world->world.ApplyLinearImpulse(entityId, impulse) ? 1 : 0);
}

PyObject* WriteSnapshot(PyObject*, PyObject* args) {
    PyObject* capsule = nullptr;
    if (!PyArg_ParseTuple(args, "O:write_snapshot", &capsule)) {
        return nullptr;
    }
    PythonWorld* world = GetWorld(capsule);
    if (world == nullptr) {
        return nullptr;
    }
    try {
        const Snapshot snapshot = world->world.WriteSnapshot();
        PyObject* result = PyDict_New();
        PyObject* entities = PyList_New(static_cast<Py_ssize_t>(snapshot.entities.size()));
        if (result == nullptr || entities == nullptr) {
            Py_XDECREF(result);
            Py_XDECREF(entities);
            return nullptr;
        }
        for (std::size_t index = 0; index < snapshot.entities.size(); ++index) {
            PyObject* entity = BodyToDictionary(snapshot.entities[index]);
            if (entity == nullptr) {
                Py_DECREF(result);
                Py_DECREF(entities);
                return nullptr;
            }
            PyList_SET_ITEM(entities, static_cast<Py_ssize_t>(index), entity);
        }
        if (!SetDictValue(result, "tick", PyLong_FromUnsignedLongLong(snapshot.tick)) ||
            !SetDictValue(result, "physics_version", PyUnicode_FromString(snapshot.physicsVersion.c_str())) ||
            !SetDictValue(
                result,
                "configuration_identity",
                PyUnicode_FromString(snapshot.configurationIdentity.c_str())) ||
            !SetDictValue(result, "terrain_identity", PyUnicode_FromString(snapshot.terrainIdentity.c_str())) ||
            PyDict_SetItemString(result, "entities", entities) != 0) {
            Py_DECREF(entities);
            Py_DECREF(result);
            return nullptr;
        }
        Py_DECREF(entities);
        return result;
    } catch (...) {
        SetCppException();
        return nullptr;
    }
}

PyObject* DrainTraceEvents(PyObject*, PyObject* args) {
    PyObject* capsule = nullptr;
    if (!PyArg_ParseTuple(args, "O:drain_trace_events", &capsule)) {
        return nullptr;
    }
    PythonWorld* world = GetWorld(capsule);
    if (world == nullptr) {
        return nullptr;
    }
    try {
        const std::vector<TraceEvent> events = world->world.DrainTraceEvents();
        PyObject* result = PyList_New(static_cast<Py_ssize_t>(events.size()));
        if (result == nullptr) {
            return nullptr;
        }
        for (std::size_t index = 0; index < events.size(); ++index) {
            PyObject* event = TraceToDictionary(events[index]);
            if (event == nullptr) {
                Py_DECREF(result);
                return nullptr;
            }
            PyList_SET_ITEM(result, static_cast<Py_ssize_t>(index), event);
        }
        return result;
    } catch (...) {
        SetCppException();
        return nullptr;
    }
}

PyObject* SetContactCandidateTracing(PyObject*, PyObject* args) {
    PyObject* capsule = nullptr;
    int enabled = 0;
    if (!PyArg_ParseTuple(args, "Op:set_contact_candidate_tracing", &capsule, &enabled)) {
        return nullptr;
    }
    PythonWorld* world = GetWorld(capsule);
    if (world == nullptr) {
        return nullptr;
    }
    world->world.SetContactCandidateTracing(enabled != 0);
    Py_RETURN_NONE;
}

PyObject* SetContactRoundRobinSeed(PyObject*, PyObject* args) {
    PyObject* capsule = nullptr;
    unsigned long long seed = 0;
    if (!PyArg_ParseTuple(args, "OK:set_contact_round_robin_seed", &capsule, &seed)) {
        return nullptr;
    }
    PythonWorld* world = GetWorld(capsule);
    if (world == nullptr) {
        return nullptr;
    }
    world->world.SetContactRoundRobinSeed(static_cast<std::uint64_t>(seed));
    Py_RETURN_NONE;
}

PyObject* ApiVersion(PyObject*, PyObject*) {
    return PyLong_FromLong(kPythonBindingApiVersion);
}

PyMethodDef kMethods[] = {
    {"api_version", ApiVersion, METH_NOARGS, "Return the native Python binding API version."},
    {
        "create_world",
        reinterpret_cast<PyCFunction>(CreateWorld),
        METH_VARARGS | METH_KEYWORDS,
        "Create an opaque portable physics world from copied terrain data.",
    },
    {
        "create_vehicle",
        reinterpret_cast<PyCFunction>(CreateVehicle),
        METH_VARARGS | METH_KEYWORDS,
        "Create a Tank or Scout using copied state and a decoded legacy collision asset.",
    },
    {
        "create_tank",
        reinterpret_cast<PyCFunction>(CreateVehicle),
        METH_VARARGS | METH_KEYWORDS,
        "Create a Tank using copied state and a decoded legacy collision asset (compatibility alias).",
    },
    {
        "create_static_collider",
        reinterpret_cast<PyCFunction>(CreateStaticCollider),
        METH_VARARGS | METH_KEYWORDS,
        "Create an immovable collision body from a decoded legacy collision asset.",
    },
    {
        "create_projectile",
        reinterpret_cast<PyCFunction>(CreateProjectile),
        METH_VARARGS | METH_KEYWORDS,
        "Create a gravity-affected dynamic projectile from a legacy collision asset.",
    },
    {"destroy_entity", DestroyEntity, METH_VARARGS, "Destroy an entity in a portable physics world."},
    {
        "submit_input",
        reinterpret_cast<PyCFunction>(SubmitInput),
        METH_VARARGS | METH_KEYWORDS,
        "Submit one sequenced vehicle input event.",
    },
    {
        "apply_authoritative_mutation",
        reinterpret_cast<PyCFunction>(ApplyAuthoritativeMutation),
        METH_VARARGS | METH_KEYWORDS,
        "Apply and collision-gate one authoritative position/orientation mutation.",
    },
    {
        "resolve_initial_spawn_pose",
        ResolveInitialSpawnPose,
        METH_VARARGS,
        "Finalize one new vehicle's terrain-safe starting pose without advancing the world.",
    },
    {"step_world", StepWorld, METH_VARARGS, "Advance one explicit authoritative physics tick."},
    {
        "trace_segment",
        reinterpret_cast<PyCFunction>(TraceSegment),
        METH_VARARGS | METH_KEYWORDS,
        "Trace a finite combat segment against terrain and registered collision bodies.",
    },
    {
        "apply_linear_impulse",
        reinterpret_cast<PyCFunction>(ApplyLinearImpulse),
        METH_VARARGS | METH_KEYWORDS,
        "Apply an authoritative world-space linear impulse to a dynamic body.",
    },
    {"write_snapshot", WriteSnapshot, METH_VARARGS, "Copy the current authoritative snapshot to Python."},
    {"drain_trace_events", DrainTraceEvents, METH_VARARGS, "Copy and clear native trace events."},
    {
        "set_contact_candidate_tracing",
        SetContactCandidateTracing,
        METH_VARARGS,
        "Enable or disable diagnostic hard-contact candidate trace events.",
    },
    {
        "set_contact_round_robin_seed",
        SetContactRoundRobinSeed,
        METH_VARARGS,
        "Set the original-style process-global contact solver seed for deterministic replay.",
    },
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef kModule = {
    PyModuleDef_HEAD_INIT,
    "_wulfram_physics",
    "Native coarse binding for WulframPhysicsCore.",
    -1,
    kMethods,
};

} // namespace

PyMODINIT_FUNC PyInit__wulfram_physics() {
    PyObject* module = PyModule_Create(&kModule);
    if (module == nullptr) {
        return nullptr;
    }
    if (PyModule_AddIntConstant(module, "API_VERSION", kPythonBindingApiVersion) != 0) {
        Py_DECREF(module);
        return nullptr;
    }
    return module;
}
