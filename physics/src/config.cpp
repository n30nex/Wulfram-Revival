#include "wulfram/physics/config.hpp"

#include <algorithm>

namespace wulfram::physics {
namespace {

UniformCurve Curve(std::initializer_list<float> samples) {
    return {std::vector<float>(samples)};
}

} // namespace

float UniformCurve::Evaluate(float input) const noexcept {
    if (samples.empty()) {
        return 0.0F;
    }
    if (samples.size() == 1 || input <= 0.0F) {
        return samples.front();
    }
    if (input >= 1.0F) {
        return samples.back();
    }
    const float inverseStep = static_cast<float>(samples.size() - 1);
    const float inputStep = 1.0F / inverseStep;
    std::size_t index = static_cast<std::size_t>(input * inverseStep);
    index = std::min(index, samples.size() - 2);
    // InterpolationTable::Evaluate (0x004DCFD0) stores the index offset, then
    // keeps the subtraction/multiply that forms the fraction in x87 until its
    // float store.  It likewise stores only the completed interpolation.
    const float indexOffset = inputStep * static_cast<float>(index);
    const float fraction = static_cast<float>(
        (static_cast<double>(input) - indexOffset) * inverseStep);
    return static_cast<float>(
        (static_cast<double>(samples[index + 1]) - samples[index]) * fraction +
        samples[index]);
}

float FeedbackTable::Evaluate(float error, float prime) const noexcept {
    const float inverseMaximumError = 1.0F / settings.absoluteMaximumError;
    const float inverseMaximumPrime = 1.0F / settings.absoluteMaximumPrime;
    float normalizedError = std::clamp(error * inverseMaximumError, -1.0F, 1.0F);
    float normalizedPrime = std::clamp(prime * inverseMaximumPrime, -1.0F, 1.0F);
    // FeedbackTable::EvaluateResponse (0x004DD070) stores each completed
    // three-factor magnitude, not the intermediate products.
    float scaledError = std::clamp(static_cast<float>(
        static_cast<double>(settings.errorMultiplier) * error * inverseMaximumError), -1.0F, 1.0F);
    float scaledPrime = std::clamp(static_cast<float>(
        static_cast<double>(inverseMaximumPrime) * settings.primeMultiplier * prime), -1.0F, 1.0F);
    const bool errorNegative = scaledError < 0.0F;
    const bool primeNegative = scaledPrime < 0.0F;
    if (errorNegative) {
        scaledError = -scaledError;
        normalizedError = -normalizedError;
    }
    if (primeNegative) {
        scaledPrime = -scaledPrime;
        normalizedPrime = -normalizedPrime;
    }
    float errorComponent = raw.Evaluate(scaledError);
    float primeComponent = -correction.Evaluate(scaledPrime);
    float primeWeightValue = 1.0F;
    float errorWeightValue = 1.0F;
    if (settings.useDamper) {
        primeWeightValue = primeWeight.Evaluate(normalizedError);
        errorWeightValue = errorWeight.Evaluate(normalizedPrime);
    }
    if (errorNegative) {
        errorComponent = -errorComponent;
    }
    if (primeNegative) {
        primeComponent = -primeComponent;
    }
    const float combined = static_cast<float>(
        static_cast<double>(primeWeightValue) * primeComponent +
        static_cast<double>(errorWeightValue) * errorComponent);
    return settings.absoluteOutput * std::clamp(combined, -1.0F, 1.0F);
}

JetProfile CurrentTankJetProfile() {
    JetProfile profile{};
    profile.fastReaction.settings = {4.0F, 1.0F, 40.0F, 1.0F, 1.25F, true};
    profile.fastReaction.raw = Curve({
        0.0F, 0.0120120123F, 0.0480480492F, 0.132692203F, 0.224828154F,
        0.335754126F, 0.449658692F, 0.528938055F, 0.584159076F, 0.624913633F,
        0.660356045F, 0.693460286F, 0.723911226F, 0.751819968F, 0.777383447F,
        0.800989091F, 0.823114157F, 0.844525218F, 0.865683913F, 0.886359751F,
        0.90623337F, 0.924931884F, 0.942305028F, 0.958539665F, 0.97359097F,
        0.987421155F, 1.0F});
    profile.fastReaction.correction = Curve({
        0.0F, 0.144173577F, 0.302859932F, 0.470509797F, 0.636041164F,
        0.782839119F, 0.888756037F, 0.909285545F, 0.923692524F,
        0.9384045F, 0.95660603F, 0.978238463F, 1.0F});
    profile.fastReaction.errorWeight = Curve({
        0.99333334F, 0.995506167F, 0.997738242F, 0.899318516F, 0.717474103F,
        0.524785757F, 0.386603415F, 0.276495755F, 0.187211051F,
        0.118616499F, 0.0686473623F, 0.0333070122F, 0.00666666683F});
    profile.fastReaction.primeWeight = Curve({
        0.99333334F, 0.993957639F, 0.99456358F, 0.995148122F, 0.995708048F,
        0.99624002F, 0.996736348F, 0.997197747F, 0.99762845F, 0.993291199F,
        0.978239536F, 0.948166132F, 0.916540027F, 0.866699397F, 0.802280664F,
        0.72506237F, 0.619817853F, 0.453863204F, 0.29249236F, 0.1657179F,
        0.0874946192F, 0.0533333346F});

    profile.slowReaction.settings = {17.5F, 1.0F, 200.0F, 1.0F, 0.400000006F, true};
    profile.slowReaction.raw = Curve({
        0.0F, 0.055936534F, 0.202003673F, 0.393509328F, 0.600000024F,
        0.73725003F, 0.844750047F, 0.941000044F, 1.0F});
    profile.slowReaction.correction = Curve({
        0.0F, 0.277452767F, 0.503050506F, 0.686936796F, 0.839255214F, 0.970149279F});
    profile.slowReaction.errorWeight = Curve({
        0.99333334F, 0.9939394F, 0.993872106F, 0.992554128F, 0.969523787F,
        0.864415526F, 0.43653658F, 0.236305863F, 0.127157226F,
        0.0679460764F, 0.0339393653F, 0.00666666683F});
    profile.slowReaction.primeWeight = Curve({
        1.0F, 1.0F, 0.861333311F, 0.544999957F, 0.221333295F,
        0.0583333112F, 0.00999999978F});

    profile.speed = Curve({
        0.99000001F, 0.991664052F, 0.993847907F, 0.996082962F,
        0.998006642F, 0.999362409F, 0.999872506F, 1.0F, 1.0F,
        0.988358498F, 0.941792607F, 0.817794979F, 0.330000013F,
        0.150000006F, 0.0900000036F, 0.0799999982F});
    profile.height = Curve({
        1.0F, 0.99851501F, 0.993987978F, 0.984253168F, 0.971088886F,
        0.958333313F, 0.949999988F, 0.933333337F, 0.883333325F,
        0.770000041F, 0.573333204F, 0.301666617F, 0.00999999978F});
    profile.heightConsider = Curve({
        0.0F, 0.0F, 0.0181818251F, 0.0496753417F, 0.0905627906F,
        0.138658032F, 0.183722973F, 0.25F, 0.428484976F, 0.762056291F,
        0.898008704F, 0.950909138F, 0.97855705F, 0.99357146F, 0.99000001F});
    profile.abate = Curve({
        1.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F,
        1.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F,
        1.0F, 1.0F, 1.0F, 0.999972582F, 0.998588085F, 0.991674304F,
        0.971727848F, 0.927067637F, 0.859086752F, 0.763676584F,
        0.648117244F, 0.521756113F, 0.394532621F, 0.275049806F,
        0.165072873F, 0.0725526437F, 0.0115924478F, 0.0F});
    profile.speedRoll = Curve({
        0.409999996F, 0.440000027F, 0.481544048F, 0.535250485F,
        0.601269424F, 0.680394113F, 0.774609089F, 0.895179749F,
        0.986387014F, 0.999809325F, 0.997712195F, 0.995317042F,
        0.993313611F, 0.991676807F, 0.99000001F});
    return profile;
}

JetProfile CurrentMedicJetProfile() {
    // The reaction, speed, and height tables are byte-for-byte equivalent to
    // the Tank copies. These four curves and the misc block are the recovered
    // vehicle-specific data loaded by the executable with the "medic" prefix.
    JetProfile profile = CurrentTankJetProfile();
    profile.heightConsider = Curve({
        0.0F, 0.00801700819F, 0.0241109319F, 0.0489243045F,
        0.0827383548F, 0.123209007F, 0.176370397F, 0.254213363F,
        0.383637458F, 0.56953615F, 0.762622893F, 0.883598447F,
        0.941074133F, 0.970485687F, 0.985054731F, 0.99000001F});
    profile.abate = Curve({
        1.0F, 0.999952316F, 0.999877036F, 0.999763072F,
        0.999577641F, 0.99930203F, 0.998955429F, 0.998565078F,
        0.998168588F, 0.997802913F, 0.99333334F, 1.0F, 1.0F,
        1.0F, 1.0F, 0.973333359F, 0.846514344F, 0.635725677F,
        0.378599226F, 0.180581897F, 0.14F});
    profile.speedRoll = Curve({
        0.393333346F, 0.446666688F, 0.538270831F, 0.650219261F,
        0.76764518F, 0.878741741F, 0.970898092F, 0.997574866F,
        0.999090552F, 0.997376025F, 0.995974302F, 0.996251404F,
        0.99633199F, 0.996446669F, 0.996680796F, 0.996974647F,
        0.997295022F, 0.997606456F, 0.997909069F, 0.998202503F,
        0.998485744F, 0.998753905F, 0.999003947F, 0.999230385F,
        0.999427676F, 0.99958992F, 0.999716759F, 0.999820054F,
        0.999900877F, 0.999960423F, 1.0F});
    profile.misc.maximumHorizontalSpeed = 95.0F;
    profile.misc.tiltMaximum = 0.90F;
    profile.misc.rollMaximum = 1.0F;
    profile.misc.rollTurnFactor = 1.0F;
    profile.misc.rollStrafeFactor = 0.70F;
    profile.misc.baseReaction = 0.005F;
    profile.misc.slopeReaction = 0.0005F;
    return profile;
}

JetShape TankRedJetShape() noexcept {
    const Vec3f down{0.0F, 0.0F, -1.0F};
    return {{{
        {{3.3345031738F, -2.5984954834F, -1.3065032959F}, down, false},
        {{3.3345031738F, 2.5984954834F, -1.3065032959F}, down, false},
        {{-4.6044921875F, -2.5984954834F, -1.3065032959F}, down, false},
        {{-4.6044921875F, 2.5984954834F, -1.3065032959F}, down, false},
    }}};
}

JetShape TankBlueJetShape() noexcept {
    const Vec3f down{0.0F, 0.0F, -1.0F};
    return {{{
        {{2.8860015869F, -2.4765014648F, -1.1499938965F}, down, false},
        {{2.8860015869F, 2.4765014648F, -1.1499938965F}, down, false},
        {{-4.5619964600F, -2.4765014648F, -1.1499938965F}, down, false},
        {{-4.5619964600F, 2.4765014648F, -1.1499938965F}, down, false},
    }}};
}

JetShape MedicRedJetShape() noexcept {
    const Vec3f down{0.0F, 0.0F, -1.0F};
    return {{{
        {{1.8584289551F, -4.1416320801F, -1.4336547852F}, down, false},
        {{1.8584289551F, 4.1416320801F, -1.4336547852F}, down, false},
        {{-2.0708007812F, -4.1416320801F, -1.4336547852F}, down, false},
        {{-2.0708007812F, 4.1416320801F, -1.4336547852F}, down, false},
    }}};
}

JetShape MedicBlueJetShape() noexcept {
    const Vec3f down{0.0F, 0.0F, -1.0F};
    return {{{
        {{1.1737976074F, -3.8948364258F, -1.2271423340F}, down, false},
        {{1.1737976074F, 3.8948364258F, -1.2271423340F}, down, false},
        {{-5.5488281250F, -3.8948364258F, -1.2271423340F}, down, false},
        {{-5.5488281250F, 3.8948364258F, -1.2271423340F}, down, false},
    }}};
}

PhysicsConfig DefaultPhysicsConfig() {
    PhysicsConfig config{};
    config.tank.jetProfile = CurrentTankJetProfile();
    config.scout.turnAdjust = 4.5;
    config.scout.moveAdjust = 85.0;
    config.scout.moveBackwardAdjust = 38.0;
    config.scout.strafeAdjust = 72.0;
    config.scout.maximumVelocity = 85.0;
    config.scout.lowFuelLevel = 2000.0;
    config.scout.maximumAltitude = 4.9;
    config.scout.maximumSpeedHeightPickup = 3.5;
    config.scout.gravityPercent = 1.0;
    config.scout.minimumJetStrength = 0.15;
    config.scout.jetResponseCoefficient = 1.1;
    config.scout.maximumFuel = 13000.0;
    // No Scout jump/fuel-regeneration values have been recovered from the
    // current client or historical server inputs used by this core.
    config.scout.jumpVelocity = 0.0;
    config.scout.jumpAcceleration = 0.0;
    config.scout.jumpFuelCost = 0.0;
    config.scout.fuelRegenerationPerSecond = 0.0;
    config.scout.activeJetFriction = 0.0F;
    config.scout.accelerationLimitScale = 1.25F;
    config.scout.jetProfile = CurrentMedicJetProfile();
    return config;
}

} // namespace wulfram::physics
